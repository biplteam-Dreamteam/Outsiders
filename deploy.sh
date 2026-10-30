#!/usr/bin/env bash
set -euo pipefail

echo "=========================================================="
echo "🚀 Grand Mobile Support Copilot — Deployment Script (VPS)"
echo "=========================================================="

# 1. Check & Install Docker if missing
if ! command -v docker &> /dev/null; then
    echo "📦 Docker not found. Installing Docker Engine..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh
    rm get-docker.sh
    sudo usermod -aG docker "$USER" || true
    echo "✅ Docker installed successfully."
fi

# 2. Check Docker Compose
if ! docker compose version &> /dev/null; then
    echo "📦 Installing docker-compose plugin..."
    sudo apt-get update && sudo apt-get install -y docker-compose-plugin
fi

# 3. Create required runtime directories
echo "📁 Preparing runtime directories..."
mkdir -p data reports models

# 4. Pull/Build and Start containers
echo "🔨 Building and starting Docker containers..."
docker compose down --remove-orphans || true
docker compose build --pull
docker compose up -d

# 5. Wait for service health
echo "⏳ Waiting for FastAPI healthcheck..."
for i in {1..30}; do
    if curl -s http://localhost:8000/health | grep -q "healthy"; then
        echo "✅ API Backend is healthy and running on port 8000!"
        break
    fi
    sleep 1
    if [ "$i" -eq 30 ]; then
        echo "⚠️ Healthcheck timed out. Checking container logs:"
        docker compose logs --tail=50 api
        exit 1
    fi
done

echo ""
echo "=========================================================="
echo "🎉 Deployment Complete!"
echo "• FastAPI Backend:       http://<YOUR_IP>:8000"
echo "• Swagger Documentation: http://<YOUR_IP>:8000/docs"
echo "• Streamlit Admin UI:    http://<YOUR_IP>:8501"
echo "=========================================================="

