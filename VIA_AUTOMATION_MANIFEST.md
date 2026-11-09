# 🚀 ПРОЕКТ «VIA АВТОМАТИЗАЦИЯ» (VIA AUTOMATION)
## Манифест команды, организационная структура и регламент взаимодействия

---

### 👑 Руководство проектом:
**Главный Управляющий (Lead Director & System Orchestrator)** — координирует всех агентов, утверждает архитектурные решения, объединяет отчеты и представляет результаты заказчику.

---

### 👥 Команда из 5 специализированных агентов:

```mermaid
flowchart TD
    LEAD["👑 Главный Управляющий (Lead Director & Orchestrator)"]
    
    subgraph QA_DIV["🧪 Отдел контроля качества и тестирования"]
        QA1["🧪 Тестировщик №1 (via_qa_tester)<br/><b>Lead Schema & Contract QA</b><br/>• 100% контракт JSON<br/>• 0% галлюцинаций правил<br/>• Мультиязычность RU/KK/UZ/EN"]
        QA2["💥 Тестировщик №2 (via_stress_tester)<br/><b>Stress & Resilience Tester</b><br/>• 20 torture-кейсов на отказ<br/>• Защита от спама и флуда<br/>• Тесты стабильности RAM и Fallback"]
    end
    
    subgraph DEV_DIV["💻 Отдел разработки и оптимизации"]
        DEV1["🐞 Кодер-Bug Hunter (via_bug_hunter)<br/><b>Senior Code Auditor</b><br/>• Аудит Python & C# кода<br/>• Поиск скрытых багов и краевых кейсов<br/>• Проверка безопасности и race conditions"]
        OPT1["⚡ Оптимизатор (via_optimizer)<br/><b>Performance & Hardware Lead</b><br/>• Тюнинг ядер CPU и многопоточности<br/>• Снижение Latency до суб-миллисекунд<br/>• Оптимизация RAM и Batch стриминга"]
    end
    
    subgraph DESIGN_DIV["🎨 Отдел дизайна и брендинга"]
        DES1["✨ Дизайнер с четким вкусом (via_aesthetic_designer)<br/><b>Elite UI/UX Aesthetics Master</b><br/>• Премиальный стиль Streamlit & WinForms<br/>• Slate-900 / Emerald / Sky палитра<br/>• Брендинг 'Via автоматизация' и эргономика"]
    end

    LEAD --> QA1
    LEAD --> QA2
    LEAD --> DEV1
    LEAD --> OPT1
    LEAD --> DES1

    QA1 -.->|"Баги контракта"| DEV1
    QA2 -.->|"Узкие места устойчивости"| OPT1
    DEV1 -.->|"Патчи логики"| QA1
    OPT1 -.->|"Ускоренный пайплайн"| QA2
    DES1 -.->|"Стили и разметка"| DEV1
```

---

### 📋 Матрица ответственности (RACI):

| Задача / Область | Главный Управляющий | Тестировщик №1 (Схемы) | Тестировщик №2 (Стресс) | Кодер (Bug Hunter) | Оптимизатор (Perf) | Дизайнер (Aesthetics) |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Стратегия и архитектура проекта** | **Accountable (A)** | Consulted (C) | Consulted (C) | Consulted (C) | Consulted (C) | Consulted (C) |
| **Проверка JSON-схемы и правил (0% галлюцинаций)** | Informed (I) | **Responsible (R)** | Consulted (C) | Consulted (C) | - | - |
| **Стресс-тесты организаторов (20 кейсов на отказ)** | Informed (I) | Consulted (C) | **Responsible (R)** | Consulted (C) | Consulted (C) | - |
| **Поиск скрытых багов и ошибок в коде** | Accountable (A) | Consulted (C) | Consulted (C) | **Responsible (R)** | Consulted (C) | - |
| **Ускорение Fast-Path (< 1 мс) и тюнинг CPU/RAM** | Accountable (A) | - | Consulted (C) | Consulted (C) | **Responsible (R)** | - |
| **Визуальный стиль, верстка, бренд и UI/UX** | Accountable (A) | - | - | Consulted (C) | - | **Responsible (R)** |
| **Релиз дистрибутива (EXE, BAT, ZIP) и Git push** | **Responsible (R)** | Consulted (C) | Consulted (C) | Consulted (C) | Consulted (C) | Consulted (C) |

---

### 🎯 Текущие боевые задачи агентов:

1. **Тестировщик №1 (`via_qa_tester`)**:
   - Полная верификация 1000 тикетов из `tickets_valid.jsonl` на соответствие контракту `verify_strict_compliance.py`.
   - Проверка категорий, приоритетов и цитирования реальных правил из `rules.json`.
   - Аудит чистоты ответов на казахском (`kk`) и узбекском (`uz`) языках.

2. **Тестировщик №2 (`via_stress_tester`)**:
   - Прогон 20 кейсов на отказ из `tests/test_organizer_torture.py` и `test_diverse_player_slang.py`.
   - Тестирование экстремальных входных потоков, спама, пустых сообщений, битого JSON.

3. **Кодер-Bug Hunter (`via_bug_hunter`)**:
   - Глубокий аудит файлов `src/pipeline.py`, `src/classifier.py`, `admin_ui.py`, `GrandCopilotApp.cs`, `Setup_GrandCopilot.cs`.
   - Поиск необработанных исключений, утечек дескрипторов, несоответствий дефолтных значений.

4. **Оптимизатор (`via_optimizer`)**:
   - Профилирование задержки каждого шага конвейера.
   - Оптимизация параллелизма в CatBoost (`thread_count`), векторизации и режима `triage_only`.
   - Минимизация выделения оперативной памяти и оптимизация сборщика мусора.

5. **Дизайнер с четким вкусом (`via_aesthetic_designer`)**:
   - Редизайн стилей веб-панели `admin_ui.py` под официальный бренд «Via автоматизация».
   - Улучшение контрастности, типографики, акцентов и анимаций в интерфейсах.
   - Проработка эстетики нативного Windows-окна `GrandCopilotApp.cs`.
