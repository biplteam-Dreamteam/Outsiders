#!/bin/bash
set -e

echo "=========================================================="
echo "🚀 Starting Grand Mobile Support Copilot Application..."
echo "=========================================================="

# 1. Start FastAPI backend on port 8000
echo "🔹 Launching FastAPI backend on port 8000..."
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2 &
FASTAPI_PID=$!

# 2. Start Streamlit Admin UI on port 8501
echo "🔹 Launching Streamlit Admin UI on port 8501..."
streamlit run admin_ui.py --server.port 8501 --server.address 0.0.0.0 --server.headless true &
STREAMLIT_PID=$!

echo "=========================================================="
echo "✅ FastAPI (PID: $FASTAPI_PID) running at http://0.0.0.0:8000"
echo "✅ Streamlit (PID: $STREAMLIT_PID) running at http://0.0.0.0:8501"
echo "=========================================================="

# Handle termination gracefully
cleanup() {
    echo "Stopping services..."
    kill -TERM "$FASTAPI_PID" "$STREAMLIT_PID" 2>/dev/null || true
    wait "$FASTAPI_PID" "$STREAMLIT_PID" 2>/dev/null || true
    exit 0
}

trap cleanup SIGTERM SIGINT

# Wait for either process to terminate
wait -n "$FASTAPI_PID" "$STREAMLIT_PID"
