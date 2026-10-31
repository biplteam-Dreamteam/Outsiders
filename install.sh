#!/usr/bin/env bash
set -euo pipefail

echo "=========================================================="
echo "📦 Grand Mobile Support Copilot — Installation & Build"
echo "=========================================================="

# 1. Check Docker
if command -v docker &> /dev/null; then
    echo "✅ Docker is installed: $(docker --version)"
else
    echo "⚠️ Docker is not found."
    echo "Attempting to install Docker Engine..."
    if command -v curl &> /dev/null; then
        curl -fsSL https://get.docker.com -o get-docker.sh
        sh get-docker.sh
        rm get-docker.sh
        sudo usermod -aG docker "$USER" || true
        echo "✅ Docker installed successfully."
    else
        echo "❌ Please install Docker manually: https://docs.docker.com/get-docker/"
        exit 1
    fi
fi

# 2. Check Docker Compose
DOCKER_COMPOSE_CMD=""
if docker compose version &> /dev/null; then
    DOCKER_COMPOSE_CMD="docker compose"
elif command -v docker-compose &> /dev/null; then
    DOCKER_COMPOSE_CMD="docker-compose"
else
    echo "⚠️ Docker Compose not found. Installing docker-compose-plugin..."
    sudo apt-get update && sudo apt-get install -y docker-compose-plugin || true
    if docker compose version &> /dev/null; then
        DOCKER_COMPOSE_CMD="docker compose"
    else
        echo "❌ Please install Docker Compose: https://docs.docker.com/compose/install/"
        exit 1
    fi
fi
echo "✅ Docker Compose is available ($DOCKER_COMPOSE_CMD)"

# 3. Create required runtime directories
echo "📁 Setting up runtime directories (data, models, reports)..."
mkdir -p data models reports

# 4. Check model weights
if [ -f "models/classifier.cbm" ] && [ -f "models/classifier_meta.joblib" ]; then
    echo "✅ Pre-trained CatBoost models found in models/ directory."
else
    echo "⚠️ Pre-trained weights not found. Running training on train dataset..."
    if [ -f "tickets_train.jsonl.gz" ] || [ -f "tickets_train.jsonl" ]; then
        if [ ! -f "data/train_labeled.csv" ]; then
            python src/prepare_dataset.py || python3 src/prepare_dataset.py
        fi
        python src/train_classifier.py || python3 src/train_classifier.py
    else
        echo "ℹ️ Note: Place tickets_train.jsonl.gz or pretrained classifier.cbm in models/."
    fi
fi

# 5. Build Docker images
echo "🔨 Building Docker images for FastAPI and Streamlit..."
$DOCKER_COMPOSE_CMD build

echo ""
echo "=========================================================="
echo "🎉 Build finished successfully!"
echo "Next step: Run './run.sh' to start all services."
echo "=========================================================="

