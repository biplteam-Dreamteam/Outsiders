# Руководство по быстрому запуску (Quickstart Guide)

Сервис полностью автономен, не требует платных облачных API и готов к запуску в один клик.

---

## 🚀 Быстрый запуск на Windows (в 1 клик)

1. **Первичная установка зависимостей:**
   Дважды кликните по файлу:
   ```cmd
   install.bat
   ```

2. **Запуск панели оператора (Web UI):**
   Дважды кликните по файлу:
   ```cmd
   start_app.bat
   ```
   В браузере автоматически откроется панель оператора: `http://localhost:8501`.

3. **Запуск сетевого REST API сервиса:**
   Дважды кликните по файлу:
   ```cmd
   start_api.bat
   ```
   В браузере откроется интерактивная документация Swagger: `http://localhost:8000/docs`.

4. **Пакетная обработка тикетов (Inference):**
   Дважды кликните по файлу:
   ```cmd
   run_predict.bat
   ```
   Либо перетащите любой `.jsonl` или `.json` файл мышкой прямо на иконку `run_predict.bat`.

---

## 🐧 Быстрый запуск на Linux / macOS

```bash
# 1. Установка зависимостей
pip install -r requirements.txt

# 2. Пакетная обработка тикетов
make predict IN=tickets_valid.jsonl OUT=pred.jsonl
# или
python predict.py --in tickets_valid.jsonl --out pred.jsonl

# 3. Верификация результатов
make verify OUT=pred.jsonl

# 4. Запуск REST API
python main.py

# 5. Запуск веб-панели оператора
streamlit run admin_ui.py
```

---

## 🐳 Запуск через Docker (Полный контейнерный стек)

```bash
docker compose up -d --build
```
Доступные сервисы:
- REST API: `http://localhost:8000` (Swagger: `http://localhost:8000/docs`)
- Веб-панель оператора: `http://localhost:8501`
- Локальная модель Qwen 2.5 3B: `http://localhost:11434`
