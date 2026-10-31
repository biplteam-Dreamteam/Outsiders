"""
Grand Mobile Support Copilot — Бонус №2: Кластеризация шаблонов
Автоматическое предложение новых шаблонов ответов по кластерам похожих обращений (категория report).
"""

import gzip
import json
import os
import sys
import time
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import orjson
from sklearn.cluster import MiniBatchKMeans
from sklearn.feature_extraction.text import TfidfVectorizer

sys.path.insert(0, os.path.abspath("."))
from src.preprocessor import normalize_cp1251_kz

STOP_WORDS_RU_EXTENDED = [
    "и", "в", "не", "на", "я", "с", "что", "а", "по", "но", "у", "за", "из", "к", "от", "до",
    "или", "ли", "да", "как", "так", "для", "это", "то", "же", "ты", "он", "она", "они", "мы",
    "вы", "меня", "мне", "мной", "пж", "пожалуйста", "админ", "помогите", "помоги", "здравствуйте",
    "привет", "добрый", "день", "вечер", "тут", "там", "очень", "еще", "ещё", "уже", "о", "об",
    "про", "под", "над", "через", "после", "перед", "между", "без", "если", "бы", "чтоб", "чтобы",
    "даже", "ни", "нет", "где", "когда", "кто", "чем", "почему", "зачем", "сколько", "какой",
    "какая", "какое", "какие", "этот", "эта", "эти", "тот", "та", "то", "те", "можете", "может",
    "хочу", "надо", "нужно", "сделайте", "скажите", "пжпж", "пжлст", "плиз", "plz", "help", "hello",
]

DOMAIN_TOPIC_RULES = [
    (
        {"застрял", "текстур", "текстурах", "текстуры", "вытащите", "провалился", "застряла", "яме"},
        "Застревание в текстурах / коллизиях карты",
        "Здравствуйте! Если вы застряли в текстурах или объектах карты, используйте команду /spawn или ожидайте: администратор уже направляется для вашей помощи.",
    ),
    (
        {"переверните", "перевернуть", "машина", "машину", "машины", "воде", "утонула", "кар", "тачка", "авто"},
        "Помощь с транспортным средством (переворот / эвакуация)",
        "Здравствуйте! Для эвакуации или переворота транспортного средства используйте меню /car -> Эвакуация. Если автомобиль застрял в недоступном месте, администратор окажет содействие.",
    ),
    (
        {"выпустите", "деморган", "кпз", "посадили", "тюрьма", "отсидел", "деморгана"},
        "Вопросы по нахождению в деморгане / КПЗ",
        "Здравствуйте! Срок в деморгане отбывается в игровом процессе. Если вы считаете выданное наказание ошибочным, оформите обращение на официальном форуме в разделе жалоб на администрацию.",
    ),
    (
        {"мут", "заглушка", "снимите", "чат", "замутили", "мута"},
        "Блокировка игрового чата (MUTE)",
        "Здравствуйте! Блокировка чата выдается за нарушение правил общения. Информацию о причине и времени окончания блокировки можно проверить в истории наказаний через меню персонажа.",
    ),
    (
        {"пароль", "аккаунт", "взлом", "восстановить", "код", "почта", "украли", "взломали"},
        "Безопасность и восстановление доступа к аккаунту",
        "Здравствуйте! Для защиты вашего аккаунта рекомендуем подключить Telegram-уведомления и Google Authenticator. Восстановить доступ можно через форму сброса пароля на экране входа.",
    ),
    (
        {"команды", "команда", "gps", "навигатор", "где", "найти", "как"},
        "Игровые команды и навигация по штату",
        "Здравствуйте! Полный перечень доступных игровых команд находится в справочнике /help. Навигация к важным точкам штата доступна через команду /gps.",
    ),
    (
        {"донат", "вип", "деньги", "покупка", "коин", "коины", "рубли", "donate", "vip"},
        "Финансовые вопросы, Донат и VIP-статус",
        "Здравствуйте! Каталог донат-услуг и актуальный баланс коинов доступны в меню /donate. Вопросы по обработке платежей решаются через официальный раздел финансовой поддержки.",
    ),
    (
        {"права", "лицензия", "лицензии", "оружие", "автошкола", "паспорт", "мед"},
        "Получение лицензий, паспорта и медицинских справок",
        "Здравствуйте! Сдать экзамен на водительские права можно в здании Автошколы (/gps -> Общественные места -> Автошкола), а паспорт выдается в Правительстве области.",
    ),
    (
        {"работа", "зарплата", "уровень", "шахта", "завод", "дальнобой", "ферма"},
        "Трудоустройство, заработок и прокачка уровня",
        "Здравствуйте! Список вакансий и уровней для трудоустройства доступен в Центре занятости населения (/gps -> Работы). Ваш текущий игровой опыт отображается в /menu.",
    ),
    (
        {"хп", "здоровье", "больница", "голод", "лечение", "аптечка", "кушать"},
        "Здоровье персонажа и медицинская помощь",
        "Здравствуйте! Восполнить здоровье можно с помощью аптечки из инвентаря либо обратившись к врачам в ближайшей больнице (/gps -> Больница).",
    ),
    (
        {"тп", "тепехни", "краш", "выбило", "релог", "кикнуло"},
        "Технические сбои и вопросы спавна",
        "Здравствуйте! Администрация не осуществляет произвольную телепортацию. В случае непредвиденного вылета из игры выберите при входе точку 'Место выхода'.",
    ),
]


def generate_template_for_cluster(top_keywords: list[str]) -> tuple[str, str]:
    """
    Определяет семантическую тему кластера и генерирует официальный шаблон ответа саппорта.
    """
    keywords_set = {k.lower() for k in top_keywords}

    for rule_keywords, topic_name, template_text in DOMAIN_TOPIC_RULES:
        # Check intersection
        if keywords_set & rule_keywords:
            return topic_name, template_text

    # Default fallback template for specialized cluster
    joined_keywords = ", ".join(top_keywords[:3])
    topic_name = f"Обращение по теме: {joined_keywords}"
    template_text = (
        f"Здравствуйте! Ваше обращение по вопросу ({joined_keywords}) принято к рассмотрению. "
        f"Администрация сервера готова предоставить подробную консультацию в игре."
    )
    return topic_name, template_text


def load_report_tickets(
    train_paths: list[str], max_samples: int = 60000
) -> list[dict[str, Any]]:
    """
    Загружает тикеты категории report из доступных источников (обычный JSONL или gzip).
    """
    reports = []
    found_path = None

    for p in train_paths:
        if os.path.exists(p):
            found_path = p
            break

    if not found_path:
        raise FileNotFoundError(
            f"Не найден датасет тикетов. Проверены пути: {train_paths}"
        )

    print(f"📖 Загрузка обращений вида 'report' из: {found_path}...")
    is_gz = found_path.endswith(".gz")
    open_fn = gzip.open if is_gz else open

    with open_fn(found_path, "rb") as f:
        for line in f:
            line_str = line.strip()
            if not line_str:
                continue
            try:
                item = orjson.loads(line_str)
            except Exception:
                continue

            if item.get("kind") == "report":
                player_msgs = [
                    m.get("text", "")
                    for m in item.get("messages", [])
                    if m.get("role") == "player"
                ]
                text = normalize_cp1251_kz(" ".join(player_msgs)).strip()
                if len(text) >= 4:
                    reports.append(
                        {
                            "ticket_id": item.get("ticket_id", ""),
                            "text": text,
                            "lang": item.get("lang")
                            or item.get("server_lang")
                            or "ru",
                        }
                    )
                    if len(reports) >= max_samples:
                        break

    return reports


def run_template_clustering(
    input_paths: list[str] | None = None,
    output_path: str = "data/suggested_templates.json",
    n_clusters: int = 20,
) -> dict[str, Any]:
    """
    Основной пайплайн кластеризации шаблонов:
    1. Извлечение текстов обращений игроков.
    2. TF-IDF векторизация с отсечением стоп-слов.
    3. Кластеризация алгоритмом MiniBatchKMeans.
    4. Определение ключевых слов и генерация шаблонов ответов.
    5. Сохранение в data/suggested_templates.json.
    """
    if input_paths is None:
        input_paths = [
            "tickets_train.jsonl",
            "tickets_train.jsonl.gz",
            "data/train_labeled.csv",
            "tickets_valid.jsonl",
        ]

    start_time = time.perf_counter()
    reports = load_report_tickets(input_paths)
    print(f"✅ Успешно извлечено {len(reports)} релевантных обращений для анализа.")

    if not reports:
        print("⚠️ Обращений не найдено.")
        return {}

    corpus = [r["text"] for r in reports]

    # 1. TF-IDF Vectorization
    print("🧠 TF-IDF векторизация текстов...")
    vectorizer = TfidfVectorizer(
        max_features=4000,
        min_df=3,
        ngram_range=(1, 2),
        stop_words=STOP_WORDS_RU_EXTENDED,
    )
    X = vectorizer.fit_transform(corpus)
    feature_names = vectorizer.get_feature_names_out()

    # 2. MiniBatchKMeans Clustering
    print(f"🎯 Кластеризация на {n_clusters} семантических кластеров (MiniBatchKMeans)...")
    kmeans = MiniBatchKMeans(
        n_clusters=n_clusters,
        random_state=42,
        batch_size=1024,
        max_iter=100,
        n_init=3,
    )
    cluster_labels = kmeans.fit_predict(X)

    # 3. Cluster Analysis & Template Synthesis
    clusters_info = []
    order_centroids = kmeans.cluster_centers_.argsort()[:, ::-1]

    # Group samples by cluster to pick representative queries
    cluster_samples: dict[int, list[str]] = {i: [] for i in range(n_clusters)}
    for idx, label in enumerate(cluster_labels):
        if len(cluster_samples[label]) < 3:
            cluster_samples[label].append(corpus[idx])

    for cluster_id in range(n_clusters):
        top_indices = order_centroids[cluster_id, :5]
        top_keywords = [feature_names[ind] for ind in top_indices]
        cluster_size = int((cluster_labels == cluster_id).sum())

        topic_name, suggested_template = generate_template_for_cluster(top_keywords)

        clusters_info.append(
            {
                "cluster_id": cluster_id,
                "cluster_size": cluster_size,
                "percentage": round((cluster_size / len(reports)) * 100, 2),
                "top_keywords": top_keywords,
                "topic": topic_name,
                "suggested_template": suggested_template,
                "sample_player_queries": cluster_samples.get(cluster_id, []),
            }
        )

    # Sort clusters by size (most popular first)
    clusters_info.sort(key=lambda c: c["cluster_size"], reverse=True)

    result_data = {
        "title": "Grand Mobile Support Copilot — Рекомендованные шаблоны ответов",
        "bonus_case": "Бонус №2: Автоматическое предложение новых шаблонов по кластерам",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_reports_analyzed": len(reports),
        "num_clusters": n_clusters,
        "clustering_algorithm": "MiniBatchKMeans + TF-IDF (1-2 ngrams)",
        "clusters": clusters_info,
    }

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as out_f:
        json.dump(result_data, out_f, ensure_ascii=False, indent=2)

    elapsed_s = time.perf_counter() - start_time
    print(f"\n🎉 Кластеризация завершена за {elapsed_s:.2f} сек!")
    print(f"📁 Результаты сохранены в: {output_path}")
    print("\nТоп-5 самых частых кластеров обращений:")
    for cl in clusters_info[:5]:
        print(f"  • [{cl['cluster_size']} тикетов ({cl['percentage']}%)]: {cl['topic']}")
        print(f"    Ключевые слова: {', '.join(cl['top_keywords'])}")
        print(f"    Шаблон: «{cl['suggested_template']}»\n")

    return result_data


if __name__ == "__main__":
    run_template_clustering()
