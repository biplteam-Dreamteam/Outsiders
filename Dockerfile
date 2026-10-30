# Multi-purpose optimized Dockerfile for Grand Mobile Support Copilot
FROM python:3.11-slim as base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY rules.json taxonomy.json ./
COPY src/ ./src/
COPY models/ ./models/
COPY app.py main.py admin_ui.py ./

# Default exposed ports: 8000 (API), 8501 (Streamlit)
EXPOSE 8000 8501

# Default command starts FastAPI backend
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
