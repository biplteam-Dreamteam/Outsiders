#!/usr/bin/env bash
set -euo pipefail

IN_FILE="${1:-tickets_valid.jsonl}"
OUT_FILE="${2:-pred.jsonl}"

echo "=========================================================="
echo "🎯 Grand Mobile Support Copilot — Batch Predictor Wrapper"
echo "📁 Input File:  $IN_FILE"
echo "💾 Output File: $OUT_FILE"
echo "=========================================================="

# Check if input file exists
if [ ! -f "$IN_FILE" ]; then
    echo "❌ Error: Input file '$IN_FILE' not found!"
    exit 1
fi

# Prefer running inside active Docker container if available
if docker compose ps --services --filter "status=running" 2>/dev/null | grep -q "api"; then
    echo "🐳 Running batch prediction inside active Docker container (api)..."
    docker compose exec -T api python predict.py --in "$IN_FILE" --out "$OUT_FILE"
elif command -v python3 &> /dev/null; then
    echo "🐍 Running batch prediction locally via python3..."
    python3 predict.py --in "$IN_FILE" --out "$OUT_FILE"
elif command -v python &> /dev/null; then
    echo "🐍 Running batch prediction locally via python..."
    python predict.py --in "$IN_FILE" --out "$OUT_FILE"
else
    echo "❌ Neither running Docker container nor Python found to execute predict.py!"
    exit 1
fi

echo ""
echo "✅ Batch prediction finished successfully!"
echo "📄 Results saved to: $OUT_FILE"

