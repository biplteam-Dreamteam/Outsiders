# Multi-purpose optimized Dockerfile for Grand Mobile Support Copilot
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code and configuration
COPY rules.json taxonomy.json setup.py ./
COPY src/ ./src/
COPY models/ ./models/
COPY app.py main.py admin_ui.py predict.py ./
COPY entrypoint.sh ./

# Build high-performance C++ core extension
RUN python setup.py build_ext --inplace

RUN chmod +x entrypoint.sh

# Expose FastAPI (8000) and Streamlit Admin UI (8501)
EXPOSE 8000 8501

# Run entrypoint script
CMD ["./entrypoint.sh"]
