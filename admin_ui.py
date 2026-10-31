import datetime
import json
import os
import sys

import streamlit as st

# Setup paths
sys.path.insert(0, os.path.abspath("."))
from src.classifier import TicketClassifier
from src.deduplicator import TicketDeduplicator
from src.guardrails import check_guardrails, sanitize_draft
from src.llm_client import LLMClient
from src.preprocessor import detect_language, extract_facts, normalize_cp1251_kz
from src.rag_engine import RAGEngine

FEEDBACK_FILE = os.path.join("data", "rlhf.jsonl")
FEEDBACK_FILE_ALT = os.path.join("data", "admin_feedback_rlhf.jsonl")
os.makedirs("data", exist_ok=True)

st.set_page_config(
    page_title="Grand Mobile Support Copilot — Admin Dashboard",
    page_icon="🛡️",
    layout="wide",
)


# Initialize engines in session state
@st.cache_resource
def load_engines():
    classifier = TicketClassifier()
    rag = RAGEngine("rules.json")
    llm = LLMClient()
    dedup = TicketDeduplicator()
    return classifier, rag, llm, dedup


classifier, rag, llm, dedup = load_engines()


def triage_ticket_sync(ticket: dict) -> dict:
    # 1. Text & Preprocessing
    player_msgs = [
        m.get("text", "")
        for m in ticket.get("messages", [])
        if m.get("role") == "player"
    ]
    raw_text = " ".join(player_msgs)
    clean_text = normalize_cp1251_kz(raw_text)

    # 2. Language
    lang = detect_language(
        clean_text, default_lang=ticket.get("lang") or ticket.get("server_lang")
    )

    # 3. Facts
    extracted = extract_facts(
        ticket, clean_text, ticket.get("rule_refs_raw"), ticket.get("images_count")
    )

    # 4. Anti-spam & Deduplication
    is_spam = dedup.check_and_update(ticket, clean_text)

    # 5. Classifier
    cls_res = classifier.predict(ticket, clean_text, extracted["has_evidence"])
    category = cls_res["category"]
    priority = cls_res["priority"]
    confidence = cls_res["confidence"]

    # 6. Guardrails
    needs_human, reasons = check_guardrails(
        ticket, clean_text, category, extracted["has_evidence"]
    )
    if cls_res["low_confidence_needs_human"]:
        needs_human = True
        reasons.append("Низкая уверенность классификатора (confidence < 0.55)")
    if is_spam:
        reasons.append("Обнаружен спам или дубликат обращения")

    # 7. RAG
    rules = rag.retrieve(
        clean_text, category=category, extracted_refs=extracted["rule_refs"], top_k=2
    )

    # 8. Draft reply
    fallback_res = llm.generate_fallback(
        lang, ticket, category, rules, extracted["nickname"]
    )
    clean_draft_text, clean_cited = sanitize_draft(
        fallback_res["text"], fallback_res["cited"], rag.get_valid_rules_dict()
    )

    return {
        "ticket_id": ticket.get("ticket_id"),
        "lang": lang,
        "category": category,
        "priority": priority,
        "is_spam_or_duplicate": is_spam,
        "extracted": extracted,
        "draft_reply": {"lang": lang, "text": clean_draft_text, "cited": clean_cited},
        "needs_human": needs_human,
        "confidence": confidence,
        "reasons": reasons,
        "retrieved_rules": rules,
        "clean_text": clean_text,
    }


def save_feedback(record: dict):
    for fpath in (FEEDBACK_FILE, FEEDBACK_FILE_ALT):
        with open(fpath, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


# UI Header
st.title("🛡️ Grand Mobile Support Copilot — Очередь тикетов")
st.markdown("Панель администратора с ИИ-триажем, RAG по правилам игры и RLHF-сигналом.")


# Load sample tickets
@st.cache_data
def load_tickets_cache():
    items = []
    file_path = "tickets_valid.jsonl"
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                items.append(json.loads(line))
                if i >= 100:  # Load first 100 for interactive UI
                    break
    return items


tickets_raw = load_tickets_cache()

# Sidebar Filters
st.sidebar.header("🔍 Фильтры очереди")
filter_prio = st.sidebar.multiselect(
    "Приоритет", ["p0", "p1", "p2", "p3"], default=["p0", "p1", "p2", "p3"]
)

# Бонус №2: Рекомендованные шаблоны по кластерам
templates_file = os.path.join("data", "suggested_templates.json")
if os.path.exists(templates_file):
    with st.sidebar.expander("💡 Шаблоны по кластерам (Бонус №2)", expanded=False):
        try:
            with open(templates_file, "r", encoding="utf-8") as tf:
                t_data = json.load(tf)
            st.caption(f"Проанализировано {t_data.get('total_reports_analyzed', 0)} обращений ({t_data.get('num_clusters', 20)} кластеров)")
            for cl in t_data.get("clusters", [])[:6]:
                st.markdown(f"**{cl['topic']}** ({cl['cluster_size']} тикетов, {cl['percentage']}%)")
                st.caption(f"Ключевые слова: {', '.join(cl['top_keywords'])}")
                st.code(cl["suggested_template"], language="text")
        except Exception as e:
            st.caption(f"Ошибка загрузки шаблонов: {e}")
filter_human = st.sidebar.selectbox(
    "Требует человека (needs_human)", ["Все", "Да (Human only)", "Нет (Auto-reply)"]
)
filter_lang = st.sidebar.multiselect(
    "Язык", ["ru", "kk", "uz", "en", "und"], default=["ru", "kk", "uz", "en", "und"]
)

# Process tickets for display
processed_queue = []
for t in tickets_raw:
    res = triage_ticket_sync(t)
    # Apply filters
    if res["priority"] not in filter_prio:
        continue
    if filter_human == "Да (Human only)" and not res["needs_human"]:
        continue
    if filter_human == "Нет (Auto-reply)" and res["needs_human"]:
        continue
    if res["lang"] not in filter_lang:
        continue
    processed_queue.append((t, res))

st.sidebar.markdown(
    f"**Найдено тикетов:** {len(processed_queue)} из {len(tickets_raw)}"
)

if not processed_queue:
    st.info("Нет тикетов, соответствующих выбранным фильтрам.")
    st.stop()

# Ticket selector
selected_idx = st.selectbox(
    "Выберите тикет из очереди:",
    options=range(len(processed_queue)),
    format_func=lambda i: (
        f"[{processed_queue[i][1]['priority'].upper()}] ID: {processed_queue[i][1]['ticket_id'][:8]} | {processed_queue[i][1]['category']} | {processed_queue[i][1]['clean_text'][:50]}..."
    ),
)

ticket_raw, t_res = processed_queue[selected_idx]

# Layout: 2 Columns
col1, col2 = st.columns([1.1, 0.9])

with col1:
    st.subheader("📋 Карточка обращения")

    # Priority & Status badges
    badge_color = {
        "p0": "🔴 **КРИТИЧНО (p0)**",
        "p1": "🟠 **ВЫСОКИЙ (p1)**",
        "p2": "🟡 **ОБЫЧНЫЙ (p2)**",
        "p3": "🟢 **НИЗКИЙ (p3)**",
    }
    st.markdown(
        f"{badge_color.get(t_res['priority'], t_res['priority'])} | **Категория:** `{t_res['category']}` | **Язык:** `{t_res['lang']}`"
    )

    if t_res["needs_human"]:
        st.error(
            f"⚠️ **Требуется вмешательство администратора!** Причины: {', '.join(t_res['reasons'])}"
        )
    else:
        st.success(
            f"✅ **Готово к автоматической отправке** (Confidence: {t_res['confidence'] * 100:.1f}%)"
        )

    if t_res["is_spam_or_duplicate"]:
        st.warning(
            "🚨 **Внимание:** Зафиксирован спам или дубликат от данного заявителя!"
        )

    st.markdown("#### 💬 Сообщения игрока")
    st.info(t_res["clean_text"])

    st.markdown("#### 🔍 Извлеченные факты (Extracted Facts)")
    f_col1, f_col2, f_col3, f_col4 = st.columns(4)
    with f_col1:
        st.metric("Никнейм", str(t_res["extracted"]["nickname"]))
    with f_col2:
        st.metric(
            "Пункты правил", ", ".join(t_res["extracted"]["rule_refs"]) or "Не указаны"
        )
    with f_col3:
        st.metric(
            "Доказательства", "Да" if t_res["extracted"]["has_evidence"] else "Нет"
        )
    with f_col4:
        st.metric("Сервер", str(t_res["extracted"]["server"] or "kz"))

    st.markdown("#### 📖 Найденные пункты правил (RAG Context)")
    if t_res["retrieved_rules"]:
        for r in t_res["retrieved_rules"]:
            with st.expander(f"Пункт {r.get('ref')}: {r.get('section')}"):
                st.write(r.get("text"))
    else:
        st.write("Специфических пунктов правил для данной категории не требуется.")

with col2:
    st.subheader("✍️ Черновик ответа (Support Reply)")

    cited_rules = t_res["draft_reply"]["cited"]
    if cited_rules:
        st.markdown(f"**Цитируемые пункты правил:** `{', '.join(cited_rules)}`")

    draft_input = st.text_area(
        "Текст ответа игроку:", value=t_res["draft_reply"]["text"], height=180
    )

    st.markdown("### Действия администратора")
    btn_col1, btn_col2, btn_col3 = st.columns(3)

    with btn_col1:
        if st.button("🚀 Отправить", use_container_width=True, type="primary"):
            save_feedback(
                {
                    "ticket_id": t_res["ticket_id"],
                    "action": "sent",
                    "final_text": draft_input,
                    "category": t_res["category"],
                    "priority": t_res["priority"],
                    "timestamp": datetime.datetime.now().isoformat(),
                }
            )
            st.success("Ответ успешно отправлен игроку!")

    with btn_col2:
        if st.button("✏️ Править", use_container_width=True):
            save_feedback(
                {
                    "ticket_id": t_res["ticket_id"],
                    "action": "edited",
                    "original_text": t_res["draft_reply"]["text"],
                    "final_text": draft_input,
                    "category": t_res["category"],
                    "priority": t_res["priority"],
                    "timestamp": datetime.datetime.now().isoformat(),
                }
            )
            st.warning("Правка сохранена как обучающий сигнал RLHF!")

    with btn_col3:
        if st.button("⚡ Эскалировать", use_container_width=True):
            save_feedback(
                {
                    "ticket_id": t_res["ticket_id"],
                    "action": "escalated",
                    "note": "Передано старшей администрации / техспециалистам",
                    "category": t_res["category"],
                    "priority": t_res["priority"],
                    "timestamp": datetime.datetime.now().isoformat(),
                }
            )
            st.info("Тикет эскалирован старшей администрации.")

    st.markdown("---")
    st.caption("Grand Mobile Support Copilot v2.0 • Decentrathon 6.0 • Case 03")
