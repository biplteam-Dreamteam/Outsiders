import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import argparse
import time

import numpy as np
import orjson

sys.path.insert(0, os.path.abspath("."))
from src.pipeline import SupportCopilotPipeline


def parse_args():
    parser = argparse.ArgumentParser(
        description="Grand Mobile Support Copilot Batch Inference"
    )
    parser.add_argument(
        "--in",
        "-i",
        dest="input_file",
        default="tickets_valid.jsonl",
        help="Input JSONL path",
    )
    parser.add_argument(
        "--out",
        "-o",
        dest="output_file",
        default="pred.jsonl",
        help="Output JSONL path",
    )
    parser.add_argument(
        "--limit",
        "-l",
        type=int,
        default=None,
        help="Optional limit of tickets to process",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    input_file = args.input_file
    output_file = args.output_file

    if not os.path.exists(input_file):
        print(f"Error: input file '{input_file}' not found.")
        sys.exit(1)

    print("=" * 65)
    print("🚀 Grand Mobile Support Copilot — Batch Predictor")
    print(f"📁 Input:  {input_file}")
    print(f"💾 Output: {output_file}")
    print("=" * 65)

    pipeline = SupportCopilotPipeline()
    latencies_ms = []

    os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)

    count = 0
    start_total_time = time.time()

    with (
        open(input_file, "r", encoding="utf-8") as in_f,
        open(output_file, "w", encoding="utf-8") as out_f,
    ):
        for line in in_f:
            line_str = line.strip()
            if not line_str:
                continue

            item = orjson.loads(line_str)

            # Measure latency per ticket
            t0 = time.perf_counter()
            pred = pipeline.triage_ticket_sync(item)
            lat_ms = (time.perf_counter() - t0) * 1000.0
            latencies_ms.append(lat_ms)

            # Write prediction line
            out_f.write(orjson.dumps(pred).decode("utf-8") + "\n")
            count += 1

            if args.limit and count >= args.limit:
                break

    total_time = time.time() - start_total_time
    avg_latency = np.mean(latencies_ms) if latencies_ms else 0.0
    p50_latency = np.percentile(latencies_ms, 50) if latencies_ms else 0.0
    p95_latency = np.percentile(latencies_ms, 95) if latencies_ms else 0.0
    p99_latency = np.percentile(latencies_ms, 99) if latencies_ms else 0.0

    # Cost Calculation: Local inference = $0.0000
    cost_per_1k = 0.0000
    total_cost = 0.0000

    print("\n✅ Processing Complete!")
    print(f"• Total processed tickets: {count}")
    print(f"• Total elapsed time:     {total_time:.2f} s")
    print(f"• Throughput:              {count / total_time:.1f} tickets/sec")
    print("\n📊 Latency Benchmark:")
    print(f"• Average Latency:         {avg_latency:.2f} ms")
    print(f"• Median (p50):            {p50_latency:.2f} ms")
    print(f"• 95th Percentile (p95):   {p95_latency:.2f} ms")
    print(f"• 99th Percentile (p99):   {p99_latency:.2f} ms")
    print("\n💰 Cost Estimation:")
    print(
        f"• Local Inference (Qwen2.5 / Fast RAG): ${total_cost:.4f} ($0.00 / 1000 tickets)"
    )
    print(f"• File saved to:           {output_file}")
    print("=" * 65)


if __name__ == "__main__":
    main()
