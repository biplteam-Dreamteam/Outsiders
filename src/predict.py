import argparse
import gc
import gzip
import json
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

from src.pipeline import SupportCopilotPipeline, load_pipeline_config

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("predict")


def parse_args():
    cfg = load_pipeline_config()
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
        default=int(cfg.get("batch_chunk_size", 64)),
        help="Batch processing chunk size (default: from admin_config.json or 64)",
    )
    parser.add_argument(
        "--mode",
        "-m",
        dest="mode",
        choices=["full", "triage_only", "copilot_only"],
        default=cfg.get("operating_mode", "full"),
        help="Operational mode: 'full' (auto/draft), 'triage_only' (classification only, ultra-fast), 'copilot_only' (human review)",
    )
    parser.add_argument(
        "--threads",
        "-t",
        dest="threads",
        type=int,
        default=int(cfg.get("cpu_threads", 8)),
        help="Number of CPU cores/threads allocated for CatBoost and inference",
    )
    parser.add_argument(
        "--ram-limit",
        dest="ram_limit_mb",
        type=int,
        default=int(cfg.get("ram_limit_mb", 2048)),
        help="Allocated RAM limit in Megabytes",
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


def is_json_array_file(filepath: str) -> bool:
    """Определяет, является ли входной файл JSON-массивом (начинается с '[')."""
    try:
        open_fn = gzip.open if filepath.endswith(".gz") else open
        with open_fn(filepath, "rt", encoding="utf-8", errors="replace") as f:
            for chunk in iter(lambda: f.read(1024), ""):
                stripped = chunk.lstrip("\ufeff \t\r\n")
                if stripped:
                    return stripped[0] == "["
    except Exception:
        pass
    return False


def stream_input_tickets(filepath: str) -> tuple[int, Any]:
    """
    Универсальный генератор входящих тикетов:
    - Поддерживает .json массив ([{...}, {...}])
    - Поддерживает .jsonl (по одной строке на тикет)
    - Поддерживает .gz сжатие
    Возвращает (total_count_or_0, generator_of_tuples(item_dict_or_none, raw_line_str))
    """
    is_array = is_json_array_file(filepath)
    open_fn = gzip.open if filepath.endswith(".gz") else open

    if is_array:
        try:
            with open_fn(filepath, "rt", encoding="utf-8", errors="replace") as f:
                data = orjson.loads(f.read())
            if isinstance(data, list):
                total = len(data)

                def gen():
                    for item in data:
                        yield item if isinstance(item, dict) else None, ""

                return total, gen()
            else:
                return 1, iter([(data if isinstance(data, dict) else None, "")])
        except Exception as exc:
            logger.warning(f"Failed to parse JSON array file: {exc}")

    # По умолчанию: построчный стриминг JSONL
    total = count_lines(filepath)

    def gen_lines():
        with open_fn(filepath, "rt", encoding="utf-8", errors="replace") as f:
            for line in f:
                line_clean = line.strip()
                if not line_clean:
                    continue
                try:
                    yield orjson.loads(line_clean), line_clean
                except Exception:
                    yield None, line_clean

    return total, gen_lines()


def main():
    args = parse_args()
    input_file = args.input_file
    output_file = args.output_file
    batch_size = max(1, args.batch_size)
    limit = args.limit
    mode = args.mode
    threads = args.threads
    ram_limit_mb = args.ram_limit_mb

    if not os.path.exists(input_file):
        # Graceful check: maybe .gz version exists or vice versa
        if not input_file.endswith(".gz") and os.path.exists(input_file + ".gz"):
            input_file = input_file + ".gz"
        elif input_file.endswith(".gz") and os.path.exists(input_file[:-3]):
            input_file = input_file[:-3]
        else:
            print(f"❌ Error: input file '{input_file}' not found.")
            sys.exit(1)

    mode_labels = {
        "full": "🟢 Полный режим (Fast-Path + Авто-ответы + Черновики)",
        "triage_only": "⚡ Чистая классификация (Triage Only — без генерации текста, сверхбыстро)",
        "copilot_only": "🛡️ Ассистент модератора (100% передача человеку с черновиками)",
    }

    print("=" * 70)
    print("🚀 Grand Mobile Support Copilot — Bulletproof Batch Predictor")
    print(f"📁 Input File:      {input_file}")
    print(f"💾 Output File:     {output_file}")
    print(f"🎛️ Mode:            {mode_labels.get(mode, mode)}")
    print(f"⚙️ CPU Threads:     {threads} cores allocated")
    print(f"🧠 RAM Limit:       {ram_limit_mb} MB")
    print(f"📦 Batch Size:      {batch_size}")
    if limit:
        print(f"🎯 Ticket Limit:    {limit}")
    print("=" * 70)

    # 1. Initialize pipeline with resource tuning
    t_init_start = time.perf_counter()
    pipeline = SupportCopilotPipeline()
    pipeline.set_operating_mode(mode)
    if hasattr(pipeline.classifier, "set_thread_count"):
        pipeline.classifier.set_thread_count(threads)
    t_init = (time.perf_counter() - t_init_start) * 1000.0
    print(f"⚙️ Pipeline initialized in {t_init:.1f} ms. Rules and CatBoost loaded.\n")

    # 2. Count total tickets for progress bar and prepare ticket stream
    total_lines, ticket_generator = stream_input_tickets(input_file)
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
        open(output_file, "wb") as out_f,
        tqdm(
            total=total_lines if total_lines > 0 else None,
            desc="🚀 Triage Processing",
            unit="ticket",
            dynamic_ncols=True,
            colour="green",
        ) as pbar,
    ):
        batch_items: list[tuple[dict[str, Any] | None, str]] = []

        def flush_batch(items: list[tuple[dict[str, Any] | None, str]]) -> None:
            nonlocal processed_count, fallback_count
            if not items:
                return

            serialized_outputs: list[bytes] = []

            for item, line_str in items:
                if item is None:
                    fallback = make_safe_fallback_response(None, ValueError("Invalid JSON format"))
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

            # Memory optimization: if aggressive GC or low RAM budget, release unreferenced objects
            if ram_limit_mb <= 2048 and processed_count % (batch_size * 4) == 0:
                gc.collect()

        # Stream tickets in batches
        for ticket_item, raw_str in ticket_generator:
            batch_items.append((ticket_item, raw_str))
            if len(batch_items) >= batch_size:
                flush_batch(batch_items)
                batch_items.clear()
                if limit and processed_count >= limit:
                    break

        # Flush any remaining items
        if batch_items and (not limit or processed_count < limit):
            flush_batch(batch_items)
            batch_items.clear()

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
    print(f"• Active Operating Mode:   {mode}")
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
