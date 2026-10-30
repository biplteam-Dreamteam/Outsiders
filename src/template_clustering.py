import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import gzip
import json
from collections import Counter
from typing import Any

from sklearn.cluster import MiniBatchKMeans
from sklearn.feature_extraction.text import TfidfVectorizer

from src.preprocessor import normalize_cp1251_kz


def discover_and_cluster_templates(
    tickets_path: str = "tickets_valid.jsonl",
    rules_path: str = "rules.json",
    num_clusters: int = 8,
    output_path: str = "reports/suggested_templates.json",
) -> dict[str, Any]:
    """
    БОНУС №2: Автоматическое предложение новых шаблонов ответов
    по кластерам похожих обращений с помощью MiniBatchKMeans + TF-IDF.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # 1. Load tickets
    tickets: list[dict[str, Any]] = []
    texts: list[str] = []

    if tickets_path.endswith(".gz"):
        opener = gzip.open(tickets_path, "rt", encoding="utf-8")
    else:
        opener = open(tickets_path, "r", encoding="utf-8")

    with opener as f:
        for line in f:
            item = json.loads(line)
            player_msgs = [
                m.get("text", "")
                for m in item.get("messages", [])
                if m.get("role") == "player"
            ]
            full_text = normalize_cp1251_kz(" ".join(player_msgs))
            if len(full_text.strip()) > 3:
                tickets.append(item)
                texts.append(full_text)
            if len(tickets) >= 5000:
                break

    if not texts:
        return {"clusters": []}

    # 2. Vectorize with TF-IDF
    vectorizer = TfidfVectorizer(
        max_features=5000, stop_words=None, ngram_range=(1, 2), min_df=2
    )
    X = vectorizer.fit_transform(texts)
    terms = vectorizer.get_feature_names_out()

    # 3. MiniBatchKMeans
    kmeans = MiniBatchKMeans(n_clusters=num_clusters, random_state=42, batch_size=256)
    cluster_labels = kmeans.fit_predict(X)

    # 4. Identify cluster topics and templates
    cluster_sizes = Counter(cluster_labels)
    order_centroids = kmeans.cluster_centers_.argsort()[:, ::-1]

    # Preload rules if available
    rules_map = {}
    if os.path.exists(rules_path):
        r_data = json.load(open(rules_path, encoding="utf-8"))
        for s in r_data.get("rules", []):
            for pt in s.get("points", []):
                ref = pt.get("ref")
                if ref and ref not in rules_map:
                    rules_map[ref] = pt.get("text", "")

    suggested_clusters = []
    for cluster_id in range(num_clusters):
        top_terms = [terms[ind] for ind in order_centroids[cluster_id, :6]]
        sample_indices = [
            i for i, lbl in enumerate(cluster_labels) if lbl == cluster_id
        ][:5]
        sample_messages = [texts[i] for i in sample_indices]
        size = cluster_sizes[cluster_id]

        # Determine theme and suggested template
        topic_str = " ".join(top_terms)
        suggested_rule_ref = "3.1"
        suggested_template = ""

        if any(w in topic_str for w in ["дм", "дб", "убил", "урон"]):
            suggested_rule_ref = "5.3"
            suggested_template = "Приветствуем, {nickname}! Жалобы на нанесение урона без причины (DM) рассматриваются строго по пункту 5.3 правил. Обязательно приложите видеофиксацию ситуации."
        elif any(w in topic_str for w in ["оск", "родн", "мат"]):
            suggested_rule_ref = "2.1"
            suggested_template = "Здравствуйте, {nickname}. Любые оскорбления личности и родственников строго запрещены пунктом 2.1 правил проекта. Нарушитель понесет соответствующее наказание."
        elif any(w in topic_str for w in ["чит", "софт", "аим", "вх"]):
            suggested_rule_ref = "5.2"
            suggested_template = "Здравствуйте, {nickname}. Использование стороннего софта запрещено пунктом 5.2 правил сервера. Жалоба передана на проверку администрации."
        elif any(w in topic_str for w in ["обман", "скам", "деньги"]):
            suggested_rule_ref = "4.1"
            suggested_template = "Приветствуем, {nickname}. Мошенничество и махинации с имуществом пресекаются пунктом 4.1. Предоставьте доказательства сделки администраторам."
        elif any(w in topic_str for w in ["застрял", "помогите", "спавн"]):
            suggested_rule_ref = "3.1"
            suggested_template = "Здравствуйте, {nickname}! Если вы застряли или попали в текстуры, воспользуйтесь /rep -> помощь, администрация окажет содействие."
        else:
            suggested_template = "Здравствуйте, {nickname}! Благодарим за обращение. По вашей теме подготовлен ответ согласно регламенту проекта Grand Mobile."

        suggested_clusters.append(
            {
                "cluster_id": cluster_id,
                "tickets_count": size,
                "percentage": round(size / len(texts) * 100, 2),
                "top_keywords": top_terms,
                "representative_samples": sample_messages[:3],
                "recommended_rule_ref": suggested_rule_ref,
                "suggested_response_template": suggested_template,
            }
        )

    # Sort by frequency descending
    suggested_clusters.sort(key=lambda x: x["tickets_count"], reverse=True)

    result = {
        "total_analyzed_tickets": len(texts),
        "clusters_count": num_clusters,
        "clusters": suggested_clusters,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"Bonus 2: Suggested templates saved to {output_path}")
    return result


if __name__ == "__main__":
    discover_and_cluster_templates()
