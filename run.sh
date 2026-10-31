#!/usr/bin/env bash
set -euo pipefail

echo "=========================================================="
echo "🚀 Grand Mobile Support Copilot — Service Launcher"
echo "=========================================================="

DOCKER_COMPOSE_CMD=""
if docker compose version &> /dev/null; then
    DOCKER_COMPOSE_CMD="docker compose"
elif command -v docker-compose &> /dev/null; then
    DOCKER_COMPOSE_CMD="docker-compose"
else
    echo "❌ Docker Compose is not installed. Run './install.sh' first."
    exit 1
fi

echo "▶️ Starting services in background..."
$DOCKER_COMPOSE_CMD up -d

echo "⏳ Verifying services availability..."
API_HOST="http://localhost:8000"
for i in {1..20}; do
    if curl -s "${API_HOST}/health" | grep -q "healthy" 2>/dev/null; then
        echo "✅ API is up and healthy!"
        break
    fi
    sleep 1
done

echo ""
echo "=========================================================="
echo "🌟 Все сервисы успешно запущены и готовы к работе!"
echo "=========================================================="
echo "• 🌐 API бэкенд (FastAPI):        http://localhost:8000"
echo "• 📖 Интерактивная Swagger-дока:  http://localhost:8000/docs"
echo "• 🛡️ Админ-панель (Streamlit):    http://localhost:8501"
echo "• 🩺 Проверка здоровья сервиса:   http://localhost:8000/health"
echo "=========================================================="
echo "Команды управления:"
echo "  Остановить сервисы: $DOCKER_COMPOSE_CMD down"
echo "  Посмотреть логи:    $DOCKER_COMPOSE_CMD logs -f"
echo "=========================================================="
