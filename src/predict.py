import argparse
import gzip
import logging
import os
import sys
import time
from typing import Any

# Ensure proper UTF-8 output encoding across all terminals and OS
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import orjson
from tqdm import tqdm

# Add project root to sys.path
sys.path.insert(0, os.path.abspath("."))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.pipeline import SupportCopilotPipeline

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("predict")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Grand Mobile Support Copilot — Bulletproof Batch Inference"
    )
    parser.add_argument(
        "--in",
        "-i",
        dest="input_file",
        default="tickets_valid.jsonl",
        help="Input JSONL file path (e.g., tickets.jsonl or tickets.jsonl.gz)",
    )
    parser.add_argument(
        "--out",
        "-o",
        dest="output_file",
        default="pred.jsonl",
        help="Output JSONL predictions file path",
    )
    parser.add_argument(
        "--batch-size",
        "-b",
        dest="batch_size",
        type=int,
        default=64,
        help="Batch processing chunk size (default: 64)",
    )
    parser.add_argument(
        "--limit",
        "-l",
        dest="limit",
        type=int,
        default=None,
        help="Optional maximum number of tickets to process",
    )
    return parser.parse_args()


def make_safe_fallback_response(raw_item: dict[str, Any] | None, exc: Exception) -> dict[str, Any]:
    """
    Пуленепробиваемый Fallback при битом JSON, сбое модели или сетевых ошибках.
    Гарантирует 100% соответствие контракту API, передачу оператору (needs_human: True)
    и нулевые галлюцинации.
    """
    item = raw_item if isinstance(raw_item, dict) else {}
    lang = item.get("lang") or item.get("server_lang") or "ru"
    if lang not in ("ru", "kk", "uz", "en"):
        lang = "ru"

    kind = str(item.get("kind", "report")).lower()
    category = "complaint.other" if kind == "complaint" else "report.offtopic"
    priority = "p2" if kind == "complaint" else "p3"

    error_msg = f"{type(exc).__name__}: {exc!s}" if str(exc) else type(exc).__name__

    return {
        "lang": lang,
        "category": category,
        "priority": priority,
        "is_spam_or_duplicate": False,
        "extracted": {
            "nickname": item.get("reported_nick"),
            "rule_refs": [],
            "has_evidence": bool(item.get("images_count", 0) and item.get("images_count", 0) > 0),
            "server": item.get("region") or item.get("server_lang"),
        },
        "draft_reply": {
            "lang": lang,
            "text": "Здравствуйте. Ваше обращение передано профильным специалистам для проверки.",
            "cited": [],
        },
        "needs_human": True,
        "confidence": 0.50,
        "reasons": [f"Ошибка обработки тикета ({error_msg}): направлен оператору"],
    }


def count_lines(filepath: str) -> int:
    """Быстрый подсчет строк в файле для корректного прогресс-бара."""
    try:
        is_gz = filepath.endswith(".gz")
        open_fn = gzip.open if is_gz else open
        with open_fn(filepath, "rb") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def open_input_stream(filepath: str):
    """Универсальное открытие обычных JSONL и сжатых .gz файлов."""
    if filepath.endswith(".gz"):
        return gzip.open(filepath, "rt", encoding="utf-8", errors="replace")
    return open(filepath, "r", encoding="utf-8", errors="replace")


def main():
    args = parse_args()
    input_file = args.input_file
    output_file = args.output_file
    batch_size = max(1, args.batch_size)
    limit = args.limit

    if not os.path.exists(input_file):
        # Graceful check: maybe .gz version exists or vice versa
        if not input_file.endswith(".gz") and os.path.exists(input_file + ".gz"):
            input_file = input_file + ".gz"
        elif input_file.endswith(".gz") and os.path.exists(input_file[:-3]):
            input_file = input_file[:-3]
        else:
            print(f"❌ Error: input file '{input_file}' not found.")
            sys.exit(1)

    print("=" * 70)
    print("🚀 Grand Mobile Support Copilot — Bulletproof Batch Predictor")
    print(f"📁 Input File:   {input_file}")
    print(f"💾 Output File:  {output_file}")
    print(f"📦 Batch Size:   {batch_size}")
    if limit:
        print(f"🎯 Ticket Limit: {limit}")
    print("=" * 70)

    # 1. Initialize pipeline
    t_init_start = time.perf_counter()
    pipeline = SupportCopilotPipeline()
    t_init = (time.perf_counter() - t_init_start) * 1000.0
    print(f"⚙️ Pipeline initialized in {t_init:.1f} ms. Rules and CatBoost loaded.\n")

    # 2. Count total tickets for progress bar
    total_lines = count_lines(input_file)
    if limit and (total_lines == 0 or total_lines > limit):
        total_lines = limit

    # Ensure output directory exists
    out_dir = os.path.dirname(os.path.abspath(output_file))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    latencies_ms: list[float] = []
    processed_count = 0
    fallback_count = 0
    start_total_time = time.time()

    # 3. Batch reading and fault-tolerant processing
    with (
        open_input_stream(input_file) as in_f,
        open(output_file, "wb") as out_f,
        tqdm(
            total=total_lines if total_lines > 0 else None,
            desc="🚀 Triage Processing",
            unit="ticket",
            dynamic_ncols=True,
            colour="green",
        ) as pbar,
    ):
        batch_lines: list[str] = []

        def flush_batch(lines: list[str]) -> None:
            nonlocal processed_count, fallback_count
            if not lines:
                return

            serialized_outputs: list[bytes] = []

            for line_str in lines:
                line_clean = line_str.strip()
                if not line_clean:
                    continue

                item: dict[str, Any] | None = None
                # Safe JSON parsing
                try:
                    item = orjson.loads(line_clean)
                except Exception as exc:
                    logger.warning(f"Corrupted JSON line encountered: {exc}")
                    fallback = make_safe_fallback_response(None, exc)
                    serialized_outputs.append(orjson.dumps(fallback) + b"\n")
                    fallback_count += 1
                    processed_count += 1
                    pbar.update(1)
                    continue

                # Safe ticket triage inference
                t0 = time.perf_counter()
                try:
                    pred = pipeline.triage_ticket_sync(item)
                except Exception as exc:
                    logger.warning(
                        f"Unhandled exception during ticket triage ({item.get('ticket_id', 'unknown')}): {exc}"
                    )
                    pred = make_safe_fallback_response(item, exc)
                    fallback_count += 1

                lat_ms = (time.perf_counter() - t0) * 1000.0
                latencies_ms.append(lat_ms)

                serialized_outputs.append(orjson.dumps(pred) + b"\n")
                processed_count += 1
                pbar.update(1)

                if limit and processed_count >= limit:
                    break

            # Write whole batch to disk
            out_f.writelines(serialized_outputs)

        # Stream file in batches
        for line in in_f:
            batch_lines.append(line)
            if len(batch_lines) >= batch_size:
                flush_batch(batch_lines)
                batch_lines.clear()
                if limit and processed_count >= limit:
                    break

        # Flush any remaining lines
        if batch_lines and (not limit or processed_count < limit):
            flush_batch(batch_lines)
            batch_lines.clear()

    total_time = max(time.time() - start_total_time, 0.0001)
    avg_latency = float(np.mean(latencies_ms)) if latencies_ms else 0.0
    p50_latency = float(np.percentile(latencies_ms, 50)) if latencies_ms else 0.0
    p95_latency = float(np.percentile(latencies_ms, 95)) if latencies_ms else 0.0
    p99_latency = float(np.percentile(latencies_ms, 99)) if latencies_ms else 0.0
    throughput = processed_count / total_time

    print("\n" + "=" * 70)
    print("🏆 INFERENCE COMPLETE — EXECUTION SUMMARY")
    print("=" * 70)
    print(f"• Total Processed Tickets: {processed_count}")
    print(f"• Safe Fallbacks Triggered: {fallback_count} ({(fallback_count / max(1, processed_count))*100:.1f}%)")
    print(f"• Total Elapsed Time:       {total_time:.2f} s")
    print(f"• Processing Throughput:    {throughput:.1f} tickets/sec")
    print("\n⚡ High-Precision Latency Benchmark:")
    print(f"• Average Latency:           {avg_latency:.2f} ms")
    print(f"• Median (p50):              {p50_latency:.2f} ms")
    print(f"• 95th Percentile (p95):     {p95_latency:.2f} ms (< 3500 ms target)")
    print(f"• 99th Percentile (p99):     {p99_latency:.2f} ms")
    print("\n💰 Economic Metrics:")
    print("• Inference Cost:            $0.0000 ($0.00 / 1000 tickets)")
    print("• LLM API Cloud Cost:        $0.0000 (100% on-premise local model)")
    print(f"• Predictions Saved to:      {output_file}")
    print("=" * 70)


if __name__ == "__main__":
    main()

