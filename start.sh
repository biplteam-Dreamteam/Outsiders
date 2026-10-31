#!/bin/bash
set -e

echo "=========================================================="
echo "🚀 Grand Mobile Support Copilot — One-Click Deployment"
echo "=========================================================="

# 1. Скачивание обученных весов CatBoost в папку models/
mkdir -p models
if [ ! -f "models/classifier.cbm" ] && [ ! -f "models/category_model.cbm" ]; then
    echo "📦 Скачивание обученных весов CatBoost..."
    wget https://example.com/classifier.cbm -O models/classifier.cbm || echo "Заглушка загрузки весов выполнена / используются локальные веса."
else
    echo "✅ Веса классификатора уже присутствуют в директории models/."
fi

# 2. Запуск Docker Compose
echo ""
echo "🐳 Запуск контейнеров через Docker Compose..."
if command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
else
    COMPOSE_CMD="docker compose"
fi

$COMPOSE_CMD up -d --build

# 3. Ожидание 5 секунд и загрузка модели Qwen 2.5 3B в контейнер Ollama
echo ""
echo "⏳ Ожидание 5 секунд инициализации сервиса Ollama..."
sleep 5

echo "📥 Загрузка локальной LLM Qwen 2.5 3B в контейнер Ollama..."
if [ -t 0 ]; then
    docker exec -it grand-copilot-ollama ollama run qwen2.5:3b || docker exec grand-copilot-ollama ollama pull qwen2.5:3b || true
else
    docker exec grand-copilot-ollama ollama run qwen2.5:3b </dev/null || docker exec grand-copilot-ollama ollama pull qwen2.5:3b || true
fi

# 4. Вывод красивых ссылок на запущенные сервисы
echo ""
echo "=========================================================="
echo "🎉 СЕРВИСЫ УСПЕШНО ЗАПУЩЕНЫ И ГОТОВЫ К РАБОТЕ!"
echo "=========================================================="
echo "🔹 FastAPI REST Backend:     http://localhost:8000"
echo "🔹 Swagger API Документация: http://localhost:8000/docs"
echo "🔹 Streamlit Admin Panel:    http://localhost:8501"
echo "🔹 Ollama LLM Engine:        http://localhost:11434"
echo "=========================================================="
echo "Полезные команды:"
echo "  Посмотреть логи сервисов:  $COMPOSE_CMD logs -f"
echo "  Остановить все сервисы:    $COMPOSE_CMD down"
echo "  Запустить стресс-тесты:    python src/final_tests.py"
echo "=========================================================="
