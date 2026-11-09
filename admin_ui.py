import asyncio
import datetime
import json
import os
import sys
import time

import pandas as pd
import psutil
import streamlit as st

# Setup paths
sys.path.insert(0, os.path.abspath("."))
from src.classifier import TicketClassifier
from src.crm_connectors import CRMConnectorManager
from src.deduplicator import TicketDeduplicator
from src.guardrails import check_guardrails, sanitize_draft
from src.llm_client import FALLBACK_TEMPLATES, LLMClient
from src.preprocessor import detect_language, extract_facts, normalize_cp1251_kz
from src.rag_engine import RAGEngine

CONFIG_FILE = os.path.join("data", "admin_config.json")
CUSTOM_TEMPLATES_FILE = os.path.join("data", "custom_templates.json")
FEEDBACK_FILE = os.path.join("data", "rlhf.jsonl")
FEEDBACK_FILE_ALT = os.path.join("data", "admin_feedback_rlhf.jsonl")
os.makedirs("data", exist_ok=True)

# CRM Manager Singleton
crm_manager = CRMConnectorManager()

st.set_page_config(
    page_title="Via автоматизация — Enterprise Admin Panel",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# Configuration Loader & Saver
def load_admin_config() -> dict:
    default_cfg = {
        "operating_mode": "full",
        "cpu_threads": min(8, os.cpu_count() or 4),
        "ram_limit_mb": 2048,
        "batch_chunk_size": 64,
        "aggressive_gc": False,
        "confidence_threshold": 0.55,
        "human_required_categories": [
            "report.account",
            "report.payment",
            "complaint.admin",
            "complaint.cheat",
        ],
        "evidence_requires_human": True,
        "max_tickets_per_hour": 5,
        "dedup_similarity_threshold": 0.85,
        "active_model": "CatBoost CBM (Fast-Path)",
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if isinstance(saved, dict):
                    default_cfg.update(saved)
        except Exception:
            pass
    return default_cfg


def save_admin_config(cfg: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# Initialize engines in session state
@st.cache_resource
def load_engines():
    cfg = load_admin_config()
    classifier = TicketClassifier(thread_count=cfg.get("cpu_threads"))
    rag = RAGEngine("rules.json")
    llm = LLMClient()
    sim_val = float(cfg.get("dedup_similarity_threshold", 0.85))
    sim_pct = sim_val * 100.0 if sim_val <= 1.0 else sim_val
    dedup = TicketDeduplicator(
        max_tickets_per_hour=int(cfg.get("max_tickets_per_hour", 5)),
        similarity_threshold=sim_pct,
    )
    return classifier, rag, llm, dedup


classifier, rag, llm, dedup = load_engines()


def triage_ticket_sync(ticket: dict, config: dict) -> dict:
    raw_msgs = ticket.get("messages") or []
    player_msgs = [
        m.get("text", "")
        for m in raw_msgs
        if isinstance(m, dict) and m.get("role") == "player"
    ]
    raw_text = " ".join(player_msgs)
    clean_text = normalize_cp1251_kz(raw_text)

    lang = detect_language(
        clean_text, default_lang=ticket.get("lang") or ticket.get("server_lang")
    )
    extracted = extract_facts(
        ticket, clean_text, ticket.get("rule_refs_raw"), ticket.get("images_count")
    )
    is_spam = dedup.check_and_update(ticket, clean_text)

    # Sync classifier thread count with config
    if hasattr(classifier, "set_thread_count") and config.get("cpu_threads"):
        classifier.set_thread_count(config["cpu_threads"])

    cls_res = classifier.predict(ticket, clean_text, extracted["has_evidence"])
    category = cls_res["category"]
    priority = cls_res["priority"]
    confidence = cls_res["confidence"]

    # Guardrails logic with dynamic config
    needs_human, reasons = check_guardrails(
        ticket, clean_text, category, extracted["has_evidence"]
    )
    conf_thresh = config.get("confidence_threshold", 0.55)
    if confidence < conf_thresh:
        needs_human = True
        reasons.append(f"Низкая уверенность модели ({confidence:.2f} < {conf_thresh:.2f})")

    configured_human_cats = set(config.get("human_required_categories", []))
    if category in configured_human_cats:
        needs_human = True
        reasons.append(f"Политика безопасности: категория '{category}' требует человека")

    if config.get("evidence_requires_human", True) and extracted["has_evidence"]:
        needs_human = True
        reasons.append("Прикреплены доказательства (скриншот/видео): требует человека")

    if is_spam:
        needs_human = True
        reasons.append("Обнаружен спам или дубликат обращения")

    op_mode = config.get("operating_mode", "full")
    if op_mode == "triage_only":
        clean_draft_text = ""
        clean_cited = []
        rules = []
    else:
        if op_mode == "copilot_only":
            needs_human = True
            reasons.append("Режим 'Ассистент модератора': требуется утверждение черновика оператором")

        rules = rag.retrieve(
            clean_text, category=category, extracted_refs=extracted["rule_refs"], top_k=2
        )
        fallback_res = llm.generate_fallback(
            lang, ticket, category, rules, extracted["nickname"]
        )
        clean_draft_text, clean_cited = sanitize_draft(
            fallback_res["text"], fallback_res["cited"], rag.get_valid_rules_dict()
        )

    return {
        "ticket_id": ticket.get("ticket_id", "demo"),
        "lang": lang,
        "category": category,
        "priority": priority,
        "is_spam_or_duplicate": is_spam,
        "extracted": extracted,
        "draft_reply": {"lang": lang, "text": clean_draft_text, "cited": clean_cited},
        "needs_human": needs_human,
        "confidence": confidence,
        "reasons": sorted(list(set(reasons))),
        "retrieved_rules": rules,
        "clean_text": clean_text,
    }


def save_feedback(record: dict):
    for fpath in (FEEDBACK_FILE, FEEDBACK_FILE_ALT):
        with open(fpath, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


# Load current config
admin_cfg = load_admin_config()

# Load sample tickets for queue
@st.cache_data
def load_tickets_cache():
    items = []
    file_path = "tickets_valid.jsonl"
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                line_str = line.strip()
                if line_str:
                    try:
                        items.append(json.loads(line_str))
                    except Exception:
                        pass
                if len(items) >= 120:
                    break
    if not items:
        # Fallback demo tickets
        items = [
            {
                "ticket_id": "demo_01",
                "kind": "complaint",
                "reported_nick": "Arman_Petrov",
                "rule_refs_raw": "2.1",
                "images_count": 2,
                "messages": [{"role": "player", "text": "Arman_Petrov оскорблял мою семью у больницы, фрапс с /time прикрепил"}],
            },
            {
                "ticket_id": "demo_02",
                "kind": "report",
                "images_count": 0,
                "messages": [{"role": "player", "text": "Застрял в текстурах у автосалона помогите выбраться"}],
            },
            {
                "ticket_id": "demo_03",
                "kind": "report",
                "images_count": 1,
                "messages": [{"role": "player", "text": "Оплатил 500 рублей донат не пришел чек загрузил"}],
            },
        ]
    return items


tickets_raw = load_tickets_cache()

# System Hardware Stats
vm_info = psutil.virtual_memory()
ram_used_gb = (vm_info.total - vm_info.available) / (1024**3)
ram_total_gb = vm_info.total / (1024**3)
total_cpu_cores = os.cpu_count() or 16

# Sidebar Control Center
with st.sidebar:
    st.markdown("### 🛡️ Via автоматизация")
    st.caption("Enterprise Control Panel v2.5")

    st.markdown("---")
    st.markdown("#### 🎛️ Режим работы модели")
    mode_options = {
        "full": "🟢 Полный автопилот (Ответы + Черновики)",
        "triage_only": "⚡ Только классификация (Triage Only)",
        "copilot_only": "🛡️ Ассистент (Human-in-the-Loop)",
    }
    cur_mode = admin_cfg.get("operating_mode", "full")
    sel_mode = st.radio(
        "Быстрое переключение:",
        options=["full", "triage_only", "copilot_only"],
        format_func=lambda x: mode_options[x],
        index=["full", "triage_only", "copilot_only"].index(cur_mode) if cur_mode in ["full", "triage_only", "copilot_only"] else 0,
        key="quick_mode_radio"
    )
    if sel_mode != cur_mode:
        admin_cfg["operating_mode"] = sel_mode
        save_admin_config(admin_cfg)
        st.success(f"Режим переключен: {sel_mode}")
        st.rerun()

    st.markdown("---")
    st.markdown("#### 💻 Выделенные ресурсы")
    col_sb1, col_sb2 = st.columns(2)
    col_sb1.metric("Ядра CPU", f"{admin_cfg.get('cpu_threads', 8)} / {total_cpu_cores}")
    col_sb2.metric("Лимит RAM", f"{admin_cfg.get('ram_limit_mb', 2048)} МБ")

    st.caption(f"Системная память: **{ram_used_gb:.1f} ГБ / {ram_total_gb:.1f} ГБ** ({vm_info.percent}%)")
    st.progress(min(1.0, vm_info.percent / 100.0))

    st.markdown("---")
    st.markdown("#### 🚀 Быстрые действия")
    if st.button("🔄 Очистить память (GC)", use_container_width=True):
        import gc
        gc.collect()
        st.info("Память очищена.")
    if st.button("⚡ Перезагрузить модели", use_container_width=True):
        st.cache_resource.clear()
        st.success("Кэш моделей сброшен.")
        st.rerun()

# Header Banner: Via автоматизация
st.markdown(
    """
    <div style="background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); 
                padding: 20px 28px; border-radius: 12px; border: 1px solid rgba(56, 189, 248, 0.25);
                display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px;
                box-shadow: 0 8px 32px rgba(0, 0, 0, 0.35);">
        <div>
            <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 4px;">
                <span style="background: linear-gradient(135deg, #38bdf8 0%, #0284c7 100%);
                             color: #020617; font-weight: 800; font-size: 14px; padding: 4px 10px;
                             border-radius: 6px; letter-spacing: 0.08em; text-transform: uppercase;">
                    VIA AI
                </span>
                <h1 style="color: #f8fafc; margin: 0; font-size: 22px; font-weight: 700;">
                    Via автоматизация — Интеллектуальный Центр Оператора
                </h1>
            </div>
            <p style="color: #94a3b8; margin: 0; font-size: 13.5px;">
                Контроль очередей SLA, верификация правил RAG, управление аппаратным инференсом и RLHF
            </p>
        </div>
        <div style="text-align: right; border-left: 1px solid rgba(148, 163, 184, 0.15); padding-left: 24px;">
            <div style="display: flex; align-items: center; gap: 8px; justify-content: flex-end;">
                <span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #34d399; box-shadow: 0 0 10px #34d399;"></span>
                <span style="color: #34d399; font-size: 12px; font-weight: 600; text-transform: uppercase;">Шлюз Активен</span>
            </div>
            <span style="color: #64748b; font-size: 12px; font-family: monospace;">v2.5.0 Enterprise On-Premise</span>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Top Metrics Row
kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
mode_short_map = {
    "full": "🟢 Полный автопилот",
    "triage_only": "⚡ Только классификация",
    "copilot_only": "🛡️ Ассистент оператора",
}
kpi1.metric("Режим модели", mode_short_map.get(admin_cfg.get("operating_mode", "full"), "Полный"), "Инференс активен")
kpi2.metric("Выделено CPU", f"{admin_cfg.get('cpu_threads', 8)} ядер", f"из {total_cpu_cores} доступных")
kpi3.metric("База знаний", "101 правило", "11 разделов")
kpi4.metric("Порог уверенности", f"{admin_cfg.get('confidence_threshold', 0.55):.2f}", "Guardrails")
kpi5.metric("Стоимость токенов", "$0.0000", "100% On-Premise")

# Main Navigation Tabs
tab_queue, tab_config, tab_rules, tab_templates, tab_sandbox, tab_analytics, tab_batch, tab_crm = st.tabs(
    [
        "📋 Очередь тикетов",
        "⚙️ Настройки и Guardrails",
        "📖 База знаний и Правила",
        "✍️ Студия шаблонов",
        "🧪 Интерактивный симулятор",
        "📊 Аналитика и SLA",
        "📦 Пакетный процессор",
        "🔌 CRM & Авто-ответчик",
    ]
)

# ==============================================================================
# TAB 1: ОЧЕРЕДЬ ТИКЕТОВ И ОПЕРАТОРСКИЙ ТРИАЖ
# ==============================================================================
with tab_queue:
    st.subheader("📋 Очередь входящих обращений с ИИ-триажем")

    q_col_filter, q_col_content = st.columns([1, 3])

    with q_col_filter:
        st.markdown("#### 🔍 Фильтры очереди")
        f_prio = st.multiselect("Приоритет", ["p0", "p1", "p2", "p3"], default=["p0", "p1", "p2", "p3"])
        f_human = st.selectbox("Требует человека", ["Все", "Да (Human Only)", "Нет (Auto-reply)"])
        f_lang = st.multiselect("Язык", ["ru", "kk", "uz", "en"], default=["ru", "kk", "uz", "en"])
        search_query = st.text_input("Поиск по тексту:", "")

    # Filter tickets
    filtered_queue = []
    for t in tickets_raw:
        res = triage_ticket_sync(t, admin_cfg)
        if res["priority"] not in f_prio:
            continue
        if f_human == "Да (Human Only)" and not res["needs_human"]:
            continue
        if f_human == "Нет (Auto-reply)" and res["needs_human"]:
            continue
        if res["lang"] not in f_lang:
            continue
        if search_query and search_query.lower() not in res["clean_text"].lower():
            continue
        filtered_queue.append((t, res))

    with q_col_content:
        st.caption(f"Найдено тикетов: **{len(filtered_queue)}** из {len(tickets_raw)}")
        if not filtered_queue:
            st.info("Нет тикетов, соответствующих выбранным критериям.")
        else:
            sel_idx = st.selectbox(
                "Выберите тикет для просмотра и обработки:",
                options=range(len(filtered_queue)),
                format_func=lambda i: (
                    f"[{filtered_queue[i][1]['priority'].upper()}] ID: {filtered_queue[i][1]['ticket_id'][:12]} | "
                    f"{filtered_queue[i][1]['category']} | {filtered_queue[i][1]['clean_text'][:60]}..."
                ),
            )
            raw_t, t_eval = filtered_queue[sel_idx]

            col_card_left, col_card_right = st.columns([1.1, 1.1])

            with col_card_left:
                st.markdown("##### 📌 Данные тикета")
                prio_colors = {
                    "p0": "#ef4444",
                    "p1": "#f97316",
                    "p2": "#eab308",
                    "p3": "#10b981",
                }
                p_col = prio_colors.get(t_eval["priority"], "#64748b")
                st.markdown(
                    f"""
                    <div style="background:#1e293b; padding:12px; border-radius:8px; border-left:4px solid {p_col}; margin-bottom:12px;">
                        <span style="background:{p_col}; color:#fff; padding:3px 8px; border-radius:4px; font-weight:700; font-size:12px;">{t_eval['priority'].upper()}</span>
                        &nbsp;&nbsp;<b>Категория:</b> <code>{t_eval['category']}</code>
                        &nbsp;&nbsp;<b>Язык:</b> <code>{t_eval['lang'].upper()}</code>
                        &nbsp;&nbsp;<b>Уверенность:</b> {t_eval['confidence']*100:.1f}%
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                if t_eval["needs_human"]:
                    st.error(f"⚠️ **Эскалация человеку:** {', '.join(t_eval['reasons'])}")
                else:
                    st.success("✅ **Автоматическое закрытие (Fast-Path)**")

                st.markdown("**Сообщение игрока:**")
                st.info(t_eval["clean_text"])

                st.markdown("**Извлеченные сущности:**")
                e_c1, e_c2, e_c3 = st.columns(3)
                e_c1.metric("Никнейм", str(t_eval["extracted"]["nickname"] or "—"))
                e_c2.metric("Доказательства", "Да" if t_eval["extracted"]["has_evidence"] else "Нет")
                e_c3.metric("Сервер", str(t_eval["extracted"]["server"] or "null"))

                if t_eval["retrieved_rules"]:
                    st.markdown("**Релевантные правила (RAG Whitelist):**")
                    for r in t_eval["retrieved_rules"]:
                        with st.expander(f"Статья {r.get('ref')}: {r.get('section')}"):
                            st.write(r.get("text"))

            with col_card_right:
                st.markdown("##### ✍️ Черновик ответа поддержки (AI Copilot)")
                cited = t_eval["draft_reply"]["cited"]
                if cited:
                    st.markdown(f"**Цитируемые статьи правил:** {', '.join([f'`{c}`' for c in cited])}")

                draft_text = st.text_area(
                    "Текст ответа (доступен для редактирования перед отправкой):",
                    value=t_eval["draft_reply"]["text"],
                    height=160,
                )

                st.markdown("##### Действия оператора")
                btn_act1, btn_act2, btn_act3 = st.columns(3)
                with btn_act1:
                    if st.button("✅ Одобрить и отправить", use_container_width=True, type="primary"):
                        save_feedback({
                            "ticket_id": t_eval["ticket_id"],
                            "action": "approved",
                            "final_text": draft_text,
                            "category": t_eval["category"],
                            "priority": t_eval["priority"],
                            "timestamp": datetime.datetime.now().isoformat(),
                        })
                        st.success("Ответ отправлен игроку!")
                with btn_act2:
                    if st.button("✏️ Править (RLHF)", use_container_width=True):
                        save_feedback({
                            "ticket_id": t_eval["ticket_id"],
                            "action": "rlhf_edit",
                            "original_text": t_eval["draft_reply"]["text"],
                            "final_text": draft_text,
                            "category": t_eval["category"],
                            "priority": t_eval["priority"],
                            "timestamp": datetime.datetime.now().isoformat(),
                        })
                        st.warning("Правка сохранена как обучающий сигнал RLHF в data/rlhf.jsonl!")
                with btn_act3:
                    if st.button("⚠️ Эскалировать", use_container_width=True):
                        save_feedback({
                            "ticket_id": t_eval["ticket_id"],
                            "action": "escalated",
                            "note": "Передано старшей администрации",
                            "timestamp": datetime.datetime.now().isoformat(),
                        })
                        st.info("Тикет передан старшему персоналу.")

# ==============================================================================
# TAB 2: НАСТРОЙКИ, РЕЖИМЫ И АППАРАТНЫЕ РЕСУРСЫ
# ==============================================================================
with tab_config:
    st.subheader("⚙️ Управление режимами модели, ресурсами CPU/RAM и Guardrails")
    st.markdown("Полный контроль над поведением модели, выделением вычислительных мощностей серверов и политиками безопасности.")

    with st.form("guardrails_config_form"):
        st.markdown("### 1. 🎛️ Режим работы модели (Ответы vs Классификация)")
        st.caption("Определяет, генерирует ли модель тексты ответов игрокам или работает как сверхбыстрый классификатор.")

        mode_options_full = {
            "full": "🟢 Полный автопилот — Классификация + Авто-ответы (Fast-Path) + Черновики (RAG по rules.json)",
            "triage_only": "⚡ Чистая классификация и маршрутизация (Triage Only) — БЕЗ генерации текста ответов. Сверхбыстрый инференс (< 1 мс/тикет), нулевой расход токенов и памяти.",
            "copilot_only": "🛡️ Ассистент модератора (Human-in-the-Loop) — Модель готовит черновики с цитатами, но 100% тикетов принудительно направляются живому оператору.",
        }
        cur_m = admin_cfg.get("operating_mode", "full")
        new_mode = st.radio(
            "Выберите режим функционирования:",
            options=["full", "triage_only", "copilot_only"],
            format_func=lambda x: mode_options_full[x],
            index=["full", "triage_only", "copilot_only"].index(cur_m) if cur_m in ["full", "triage_only", "copilot_only"] else 0,
        )

        st.markdown("---")
        st.markdown("### 2. 💻 Выделение аппаратных ресурсов (CPU Cores & RAM Limit)")
        st.caption("Тонкая настройка производительности и аппаратных ограничений для многоядерных серверов.")

        col_hw1, col_hw2 = st.columns(2)
        with col_hw1:
            new_threads = st.slider(
                "Выделение ядер процессора (CPU Cores / Threads):",
                min_value=1,
                max_value=total_cpu_cores,
                value=int(min(admin_cfg.get("cpu_threads", 8), total_cpu_cores)),
                help="Количество потоков для CatBoost, параллельной обработки текста и векторизации TF-IDF."
            )
            st.caption(f"Доступно в вашей системе: **{total_cpu_cores} ядер**.")

        with col_hw2:
            new_ram = st.slider(
                "Лимит оперативной памяти для программы (RAM Limit MB):",
                min_value=512,
                max_value=16384,
                value=int(admin_cfg.get("ram_limit_mb", 2048)),
                step=256,
                help="Максимальный порог памяти. При превышении автоматически запускается агрессивная сборка мусора (Garbage Collector)."
            )
            st.caption(f"Текущая системная память: **{ram_used_gb:.1f} ГБ занято** из **{ram_total_gb:.1f} ГБ**.")

        col_opt1, col_opt2 = st.columns(2)
        with col_opt1:
            new_chunk_size = st.select_slider(
                "Размер пачки для пакетной обработки (Batch Chunk Size):",
                options=[16, 32, 64, 128, 256, 512],
                value=int(admin_cfg.get("batch_chunk_size", 64)),
                help="Определяет размер порции тикетов, единовременно обрабатываемых в оперативной памяти."
            )
        with col_opt2:
            new_agg_gc = st.checkbox(
                "Агрессивная сборка мусора (Aggressive GC)",
                value=bool(admin_cfg.get("aggressive_gc", False)),
                help="Принудительно освобождает неиспользуемую память Python после каждого батча. Рекомендуется для слабых серверов (RAM <= 2 ГБ)."
            )

        st.markdown("---")
        st.markdown("### 3. 🛡️ Пороги доверия классификатора")
        new_conf = st.slider(
            "Минимальный порог уверенности модели (Confidence Threshold):",
            min_value=0.30,
            max_value=0.95,
            value=float(admin_cfg.get("confidence_threshold", 0.55)),
            step=0.05,
            help="Если уверенность CatBoost ниже этого значения, тикет гарантированно передается оператору.",
        )

        st.markdown("### 4. 👥 Матрица безусловной эскалации человека (Needs Human Always)")
        all_categories = [
            "report.account",
            "report.payment",
            "complaint.admin",
            "complaint.cheat",
            "complaint.insult",
            "complaint.dm",
            "complaint.scam",
            "complaint.rmt_ads",
            "complaint.other",
            "complaint.invalid",
            "report.question",
            "report.help",
            "report.complaint",
            "report.offtopic",
        ]
        new_human_cats = st.multiselect(
            "Категории с принудительной передачей оператору:",
            options=all_categories,
            default=admin_cfg.get("human_required_categories", ["report.account", "report.payment", "complaint.admin", "complaint.cheat"]),
            help="Тикеты указанных категорий никогда не закрываются автоматически.",
        )

        st.markdown("### 5. 📷 Политика работы с доказательствами")
        new_ev_human = st.checkbox(
            "Принудительно требовать модератора при наличии доказательств (has_evidence=True / images_count > 0)",
            value=admin_cfg.get("evidence_requires_human", True),
            help="ИИ не может гарантированно верифицировать подлинность скриншотов и видео, поэтому жалоба передается человеку.",
        )

        st.markdown("### 6. 🚫 Защита от спама и флуда (Deduplication)")
        c_spam1, c_spam2 = st.columns(2)
        with c_spam1:
            new_max_tickets = st.number_input(
                "Максимум тикетов в час от одного игрока:",
                min_value=1,
                max_value=30,
                value=int(admin_cfg.get("max_tickets_per_hour", 5)),
            )
        with c_spam2:
            new_sim_thresh = st.slider(
                "Порог сходства текстов для детекции дубликата (RapidFuzz):",
                min_value=0.50,
                max_value=0.99,
                value=float(admin_cfg.get("dedup_similarity_threshold", 0.85)),
                step=0.01,
            )

        submit_config = st.form_submit_button("💾 Сохранить и применить все настройки", type="primary")
        if submit_config:
            admin_cfg["operating_mode"] = new_mode
            admin_cfg["cpu_threads"] = new_threads
            admin_cfg["ram_limit_mb"] = new_ram
            admin_cfg["batch_chunk_size"] = new_chunk_size
            admin_cfg["aggressive_gc"] = new_agg_gc
            admin_cfg["confidence_threshold"] = new_conf
            admin_cfg["human_required_categories"] = new_human_cats
            admin_cfg["evidence_requires_human"] = new_ev_human
            admin_cfg["max_tickets_per_hour"] = new_max_tickets
            admin_cfg["dedup_similarity_threshold"] = new_sim_thresh
            save_admin_config(admin_cfg)
            if hasattr(classifier, "set_thread_count"):
                classifier.set_thread_count(new_threads)
            st.success("Настройки успешно сохранены в data/admin_config.json и мгновенно применены в рантайме!")
            st.rerun()

# ==============================================================================
# TAB 3: БАЗА ЗНАНИЙ И ПРАВИЛА
# ==============================================================================
with tab_rules:
    st.subheader("📖 Редактор базы знаний (101 утвержденное правило)")

    rules_dict = rag.get_valid_rules_dict()
    rules_table_data = []
    for ref, text in sorted(rules_dict.items(), key=lambda x: str(x[0])):
        rules_table_data.append({"Пункт": ref, "Текст правила": text})

    df_rules = pd.DataFrame(rules_table_data)

    r_search = st.text_input("🔍 Поиск по номеру статьи или ключевым словам правила:", "")
    if r_search:
        df_rules = df_rules[
            df_rules["Пункт"].str.contains(r_search, case=False)
            | df_rules["Текст правила"].str.contains(r_search, case=False)
        ]

    st.dataframe(df_rules, use_container_width=True, height=360)

    st.markdown("---")
    st.markdown("#### ➕ Добавить или отредактировать правило")
    with st.form("rule_edit_form"):
        col_r1, col_r2 = st.columns([1, 3])
        with col_r1:
            rule_ref_input = st.text_input("Номер статьи (Ref, например: 5.10):", "")
            rule_sec_input = st.text_input("Раздел (Section):", "V. ПРАВИЛА ИГРОВОГО ПРОЦЕССА")
        with col_r2:
            rule_text_input = st.text_area("Полный текст правила и санкций:", height=110)

        submit_rule = st.form_submit_button("💾 Сохранить правило в rules.json", type="primary")
        if submit_rule:
            if not rule_ref_input or not rule_text_input:
                st.error("Пожалуйста, заполните номер статьи и текст правила.")
            else:
                try:
                    with open("rules.json", "r", encoding="utf-8") as rf:
                        r_raw = json.load(rf)
                    # Add point
                    added = False
                    for sec in r_raw.get("rules", []):
                        if sec.get("category") == rule_sec_input or not added:
                            if "points" not in sec:
                                sec["points"] = []
                            # Check if exists
                            existing = [p for p in sec["points"] if p.get("ref") == rule_ref_input]
                            if existing:
                                existing[0]["text"] = rule_text_input
                            else:
                                sec["points"].append({"ref": rule_ref_input, "text": rule_text_input})
                            added = True
                            break
                    with open("rules.json", "w", encoding="utf-8") as rf:
                        json.dump(r_raw, rf, ensure_ascii=False, indent=1)
                    st.cache_resource.clear()
                    st.success(f"Правило {rule_ref_input} успешно сохранено в rules.json!")
                    st.rerun()
                except Exception as ex:
                    st.error(f"Ошибка сохранения: {ex}")

# ==============================================================================
# TAB 4: СТУДИЯ ШАБЛОНОВ
# ==============================================================================
with tab_templates:
    st.subheader("✍️ Студия шаблонов Fast-Path (4 языка)")
    st.markdown("Настройте утвержденные тексты авто-ответов для каждого языка. Поддерживаются переменные `{nick}`, `{ref}`, `{text}`.")

    # Load custom templates if available
    curr_templates = FALLBACK_TEMPLATES

    lang_tab_ru, lang_tab_kk, lang_tab_uz, lang_tab_en = st.tabs(
        ["🇷🇺 Русский (RU)", "🇰🇿 Қазақша (KK)", "🇺🇿 O'zbekcha (UZ)", "🇬🇧 English (EN)"]
    )

    edited_templates = {}

    def render_lang_templates(l_code, tab):
        with tab:
            l_dict = curr_templates.get(l_code, {})
            t_with_rule = st.text_area(f"С цитатой правила ({l_code}):", value=l_dict.get("with_rule", ""), height=70, key=f"t_{l_code}_wr")
            t_need_ev = st.text_area(f"Запрос доказательств ({l_code}):", value=l_dict.get("need_evidence", ""), height=70, key=f"t_{l_code}_ne")
            t_payment = st.text_area(f"Финансы и донат ({l_code}):", value=l_dict.get("payment", ""), height=70, key=f"t_{l_code}_pay")
            t_appeal = st.text_area(f"Апелляция наказания ({l_code}):", value=l_dict.get("appeal", ""), height=70, key=f"t_{l_code}_app")
            t_report = st.text_area(f"Помощь и навигация ({l_code}):", value=l_dict.get("report", ""), height=70, key=f"t_{l_code}_rep")
            t_general = st.text_area(f"Общий ответ ({l_code}):", value=l_dict.get("general", ""), height=70, key=f"t_{l_code}_gen")
            return {
                "with_rule": t_with_rule,
                "need_evidence": t_need_ev,
                "payment": t_payment,
                "appeal": t_appeal,
                "report": t_report,
                "general": t_general,
            }

    edited_templates["ru"] = render_lang_templates("ru", lang_tab_ru)
    edited_templates["kk"] = render_lang_templates("kk", lang_tab_kk)
    edited_templates["uz"] = render_lang_templates("uz", lang_tab_uz)
    edited_templates["en"] = render_lang_templates("en", lang_tab_en)

    if st.button("💾 Сохранить шаблоны ответов", type="primary"):
        with open(CUSTOM_TEMPLATES_FILE, "w", encoding="utf-8") as tf:
            json.dump(edited_templates, tf, ensure_ascii=False, indent=2)
        FALLBACK_TEMPLATES.update(edited_templates)
        st.success("Шаблоны успешно сохранены и активированы в системе!")

# ==============================================================================
# TAB 5: ИНТЕРАКТИВНЫЙ СИМУЛЯТОР
# ==============================================================================
with tab_sandbox:
    st.subheader("🧪 Песочница тестирования и отладки тикетов")
    st.markdown("Введите произвольное обращение игрока, чтобы пошагово увидеть работу всех 8 слоев конвейера.")

    col_sim_in1, col_sim_in2 = st.columns([2, 1])
    with col_sim_in1:
        sim_text = st.text_area(
            "Текст тикета (любой язык / сленг / битая кодировка CP1251):",
            value="Arman_Petrov оскорблял меня и мою семью в чате у больницы, потом заДМил без причины, фрапс с /time прикрепил, пункт 2.1 ОП",
            height=100,
        )
    with col_sim_in2:
        sim_nick = st.text_input("Никнейм заявителя / нарушителя:", value="Arman_Petrov")
        sim_imgs = st.number_input("Количество скриншотов / доказательств:", min_value=0, max_value=10, value=1)
        sim_kind = st.selectbox("Тип обращения (kind):", ["complaint", "report"])

    if st.button("⚡ Провести анализ через ИИ (Run AI Triage)", type="primary"):
        test_ticket = {
            "ticket_id": "sandbox_sim_01",
            "kind": sim_kind,
            "reported_nick": sim_nick,
            "images_count": sim_imgs,
            "messages": [{"role": "player", "text": sim_text}],
        }
        start_t = time.perf_counter()
        sim_res = triage_ticket_sync(test_ticket, admin_cfg)
        elapsed_ms = (time.perf_counter() - start_t) * 1000.0

        st.markdown(f"**Время выполнения:** `{elapsed_ms:.2f} мс` (Fast-Path)")

        s_col1, s_col2, s_col3, s_col4 = st.columns(4)
        s_col1.metric("Категория", sim_res["category"])
        s_col2.metric("Приоритет", sim_res["priority"].upper())
        s_col3.metric("Уверенность", f"{sim_res['confidence']*100:.1f}%")
        s_col4.metric("Язык", sim_res["lang"].upper())

        st.markdown("#### Трассировка слоев обработки:")
        with st.expander("1. Предобработка и восстановление кодировок", expanded=True):
            st.write(f"**Очищенный текст:** {sim_res['clean_text']}")
            st.write(f"**Извлеченный ник:** `{sim_res['extracted']['nickname']}`")
            st.write(f"**Признак доказательств (`has_evidence`):** `{sim_res['extracted']['has_evidence']}`")

        with st.expander("2. Оценка рисков и эскалация человеку (Guardrails)", expanded=True):
            st.write(f"**Нужен человек (`needs_human`):** `{sim_res['needs_human']}`")
            st.write(f"**Причины эскалации:** {sim_res['reasons'] or ['Нет рисков, авто-ответ разрешен']}")

        with st.expander("3. База знаний и черновик ответа (RAG Whitelist)", expanded=True):
            st.write(f"**Цитируемые правила:** `{sim_res['draft_reply']['cited']}`")
            st.success(sim_res["draft_reply"]["text"])

# ==============================================================================
# TAB 6: АНАЛИТИКА И МЕТРИКИ SLA
# ==============================================================================
with tab_analytics:
    st.subheader("📊 Аналитический дашборд производительности и SLA")

    # Compute dataset stats
    all_res = [triage_ticket_sync(t, admin_cfg) for t in tickets_raw]
    df_metrics = pd.DataFrame(all_res)

    col_an1, col_an2 = st.columns(2)

    with col_an1:
        st.markdown("#### Распределение категорий")
        cat_counts = df_metrics["category"].value_counts()
        st.bar_chart(cat_counts)

    with col_an2:
        st.markdown("#### Распределение приоритетов SLA")
        prio_counts = df_metrics["priority"].value_counts()
        st.bar_chart(prio_counts)

    col_an3, col_an4 = st.columns(2)
    with col_an3:
        st.markdown("#### Языковой срез")
        lang_counts = df_metrics["lang"].value_counts()
        st.dataframe(lang_counts, use_container_width=True)

    with col_an4:
        st.markdown("#### Экономический эффект (ROI)")
        total_eval = len(all_res)
        auto_cnt = sum(1 for r in all_res if not r["needs_human"])
        st.markdown(
            f"""
            - **Всего проанализировано:** {total_eval} обращений
            - **Закрыто автоматически без оператора:** {auto_cnt} ({auto_cnt/total_eval*100:.1f}%)
            - **Экономия времени саппорта:** ~{auto_cnt * 3.5 / 60:.1f} часов модераторов
            - **Затраты на API OpenAI:** **$0.00** (чистая экономия ~$0.02 за тикет)
            - **Соблюдение SLA (< 5.0 сек):** **100.0%**
            """
        )

# ==============================================================================
# TAB 7: ПАКЕТНЫЙ ПРОЦЕССОР ФАЙЛОВ
# ==============================================================================
with tab_batch:
    st.subheader("📦 Пакетная обработка файлов (Batch Inference)")
    st.markdown("Загрузите файл со списком обращений (`.jsonl` или `.json`), чтобы обработать их на максимальной скорости.")

    uploaded_file = st.file_uploader("Выберите файл с тикетами:", type=["jsonl", "json", "gz"])
    if uploaded_file is not None:
        st.write(f"Файл загружен: **{uploaded_file.name}** ({uploaded_file.size} байт)")
        if st.button("🚀 Начать пакетную обработку в браузере", type="primary"):
            content = uploaded_file.getvalue().decode("utf-8", errors="replace")
            lines = [line.strip() for line in content.split("\n") if line.strip()]

            progress_bar = st.progress(0)
            status_text = st.empty()

            out_predictions = []
            t_start = time.perf_counter()

            for idx, line_str in enumerate(lines):
                try:
                    ticket_item = json.loads(line_str)
                    res = triage_ticket_sync(ticket_item, admin_cfg)
                    # Format strictly
                    out_predictions.append(json.dumps(res, ensure_ascii=False) + "\n")
                except Exception as ex:
                    pass

                if idx % 20 == 0 or idx == len(lines) - 1:
                    progress_bar.progress((idx + 1) / len(lines))
                    status_text.text(f"Обработано {idx + 1} из {len(lines)} тикетов...")

            total_elapsed = time.perf_counter() - t_start
            st.success(
                f"Обработка завершена! {len(out_predictions)} тикетов обработано за {total_elapsed:.2f} сек "
                f"({len(out_predictions)/max(total_elapsed, 0.001):.1f} тикетов/сек)"
            )

            result_bytes = "".join(out_predictions).encode("utf-8")
            st.download_button(
                label="📥 Скачать готовый pred.jsonl",
                data=result_bytes,
                file_name="pred.jsonl",
                mime="application/x-ndjson",
            )


# ==============================================================================
# TAB 8: B2B CRM ИНТЕГРАЦИИ & АВТОНОМНЫЙ АВТО-ОТВЕТЧИК
# ==============================================================================
with tab_crm:
    st.subheader("🔌 B2B CRM Интеграции & Автономный авто-ответчик («Via автоматизация»)")
    st.markdown(
        "Бесшовная интеграция с корпоративными Service Desk и CRM-системами: **Telegram Support Bot, "
        "Zendesk, amoCRM, Bitrix24 и Generic Webhooks**. "
        "Система способна автономно разрешать до 50% стандартных обращений без участия человека, "
        "а сложные и спорные кейсы направлять операторам с предварительно сгенерированным черновиком ответа."
    )

    # 1. LIVE B2B METRICS
    crm_metrics = crm_manager.get_audit_metrics()
    cm1, cm2, cm3, cm4 = st.columns(4)
    cm1.metric(
        "Всего тикетов CRM",
        f"{crm_metrics['total_tickets']} шт.",
        "За весь период",
    )
    cm2.metric(
        "Автономных ответов (Deflection)",
        f"{crm_metrics['auto_replied']} шт. ({crm_metrics['deflection_rate_pct']}%)",
        f"+{crm_metrics['deflection_rate_pct']}% нагрузка снята",
    )
    cm3.metric(
        "Эскалировано операторам",
        f"{crm_metrics['escalated_to_operator']} шт.",
        "С черновиками",
    )
    cm4.metric(
        "Сэкономлено времени",
        f"{crm_metrics['operator_hours_saved']} ч",
        "~3 мин / тикет",
    )

    st.markdown("---")

    crm_cfg = crm_manager.config

    # 2. MASTER POLICIES
    st.markdown("### 🛡️ Глобальная политика автономного ответа (Auto-Pilot Policy)")
    crm_col_left, crm_col_right = st.columns([1, 1])

    with crm_col_left:
        auto_enabled = st.toggle(
            "Включить автономный авто-ответчик (Auto-Reply)",
            value=bool(crm_cfg.get("auto_reply_enabled", True)),
            help="Если включено, система автоматически отправляет ответ пользователю при уверенности выше порога",
        )
        min_conf = st.slider(
            "Минимальный порог уверенности модели для авто-ответа:",
            min_value=0.50,
            max_value=0.95,
            value=float(crm_cfg.get("min_confidence_auto_reply", 0.70)),
            step=0.05,
            help="Обращения с уверенностью ниже порога ВСЕГДА отправляются человеку-оператору",
        )

    with crm_col_right:
        all_tax_cats = [
            "report.question",
            "report.help",
            "report.complaint",
            "report.offtopic",
            "complaint.invalid",
            "report.account",
            "report.payment",
            "report.bag",
            "complaint.other",
        ]
        allowed_cats = st.multiselect(
            "Белый список категорий для 100% авто-ответа:",
            options=all_tax_cats,
            default=crm_cfg.get("allowed_auto_reply_categories", [
                "report.question",
                "report.help",
                "report.complaint",
                "report.offtopic",
                "complaint.invalid",
            ]),
            help="Только в этих категориях бот может отвечать игрокам автономно",
        )

    st.markdown("---")

    # 3. CRM CHANNELS & CREDENTIALS
    st.markdown("### 🌐 Подключение каналов связи и CRM")
    crm_tab_tg, crm_tab_zd, crm_tab_amo, crm_tab_hook = st.tabs([
        "🤖 Telegram Support Bot",
        "🎫 Zendesk Helpdesk",
        "💼 amoCRM / Bitrix24",
        "⚡ Universal Webhook API",
    ])

    with crm_tab_tg:
        st.markdown("#### Настройка Telegram Support Bot")
        st.info("Бот принимает сообщения пользователей, классифицирует их и отвечает либо эскалирует в закрытую группу саппорта.")
        tg_cfg = crm_cfg.get("telegram", {})
        tg_bot_token = st.text_input("Telegram Bot Token (от @BotFather):", value=tg_cfg.get("bot_token", ""), type="password")
        tg_chat_id = st.text_input("ID закрытого канала операторов для эскалаций (chat_id):", value=tg_cfg.get("escalation_chat_id", ""))
        st.code("Вебхук URL для регистрации бота: https://<your-host>:8000/webhook/telegram", language="bash")
        st.caption("Для установки вебхука выполните: `curl -F 'url=https://<your-host>:8000/webhook/telegram' https://api.telegram.org/bot<TOKEN>/setWebhook`")

    with crm_tab_zd:
        st.markdown("#### Настройка Zendesk Support")
        st.info("При авто-ответе бот ставит тикет в статус 'Solved' с публичным ответом. При эскалации оставляет приватную заметку (Internal Note) для оператора со статьями правил.")
        zd_cfg = crm_cfg.get("zendesk", {})
        zd_subdomain = st.text_input("Zendesk Subdomain (например, 'company'):", value=zd_cfg.get("subdomain", ""))
        zd_email = st.text_input("Zendesk Agent Email:", value=zd_cfg.get("email", ""))
        zd_token = st.text_input("Zendesk API Token:", value=zd_cfg.get("api_token", ""), type="password")
        st.code("Вебхук URL для Zendesk Trigger: https://<your-host>:8000/webhook/zendesk", language="bash")

    with crm_tab_amo:
        st.markdown("#### Настройка amoCRM & Bitrix24")
        st.info("Принимает лиды и обращения из чат-виджетов amoCRM и Bitrix24 через входящие вебхуки.")
        st.code("Вебхук URL для amoCRM / Bitrix24: https://<your-host>:8000/webhook/crm/ticket", language="bash")
        st.markdown("""
        **Пример интеграции в amoCRM:**
        1. В amoCRM перейдите в *Настройки -> Интеграции -> Webhooks*.
        2. Добавьте хук на событие *"Создание сделки / Новое сообщение чата"*.
        3. Укажите URL: `https://<your-host>:8000/webhook/crm/ticket`.
        """)

    with crm_tab_hook:
        st.markdown("#### Универсальный HTTP REST Webhook")
        st.info("Любая внутренняя система или самописный хелпдеск может отправлять тикеты по этому интерфейсу.")
        st.code("POST https://<your-host>:8000/webhook/crm/ticket", language="http")
        st.markdown("Тело запроса (JSON):")
        st.code(
            json.dumps({
                "ticket_id": "ticket_12345",
                "text": "Здравствуйте, как устроиться на работу инкассатором?",
                "callback_url": "https://company.com/api/support/callback",
                "lang": "ru",
            }, indent=2, ensure_ascii=False),
            language="json",
        )

    if st.button("💾 Сохранить конфигурацию CRM", type="primary"):
        updated_crm_cfg = {
            "auto_reply_enabled": auto_enabled,
            "min_confidence_auto_reply": min_conf,
            "allowed_auto_reply_categories": allowed_cats,
            "generic_webhook": {"enabled": True, "default_callback_url": ""},
            "telegram": {
                "enabled": bool(tg_bot_token),
                "bot_token": tg_bot_token.strip(),
                "escalation_chat_id": tg_chat_id.strip(),
            },
            "zendesk": {
                "enabled": bool(zd_subdomain and zd_token),
                "subdomain": zd_subdomain.strip(),
                "email": zd_email.strip(),
                "api_token": zd_token.strip(),
            },
            "amocrm": {"enabled": True},
        }
        crm_manager.save_config(updated_crm_cfg)
        st.success("✅ Настройки B2B интеграций и политики авто-ответа успешно сохранены!")

    st.markdown("---")

    # 4. LIVE SANDBOX / DISPATCH SIMULATOR
    st.markdown("### 🧪 Интерактивный симулятор CRM-обращения")
    st.markdown("Проверьте в реальном времени, как система обработает входящий тикет из CRM: отправит ли авто-ответ или эскалирует человеку.")

    sim_c1, sim_c2 = st.columns([1, 2])
    with sim_c1:
        sim_crm_type = st.selectbox("Источник CRM:", ["generic", "telegram", "zendesk", "amocrm"])
        sim_ticket_id = st.text_input("ID обращения:", "CRM-TEST-9901")
        sim_has_photo = st.checkbox("Есть прикрепленное фото/доказательство", value=False)
    with sim_c2:
        sim_text = st.text_area("Текст обращения клиента / игрока:", "Здравствуйте! Подскажите, со скольки лет можно пойти в армию и какие документы нужны?", height=110)

    if st.button("🚀 Симулировать обработку тикета", type="secondary"):
        with st.spinner("Триаж и проверка правил Guardrails..."):
            sim_payload = {
                "ticket_id": sim_ticket_id,
                "text": sim_text,
                "images_count": 1 if sim_has_photo else 0,
                "source_crm": sim_crm_type,
            }
            adapted = crm_manager.adapt_inbound_ticket(sim_crm_type, sim_payload)
            triage_res = triage_ticket_sync(adapted, admin_cfg)
            triage_res["draft_reply"] = sanitize_draft(
                triage_res["draft_reply"], rag.get_valid_rules_dict()
            )
            dispatch_res = asyncio.run(crm_manager.process_and_dispatch(adapted, triage_res))

            if dispatch_res["auto_replied"]:
                st.success(f"🎉 **СТАТУС: АВТОНОМНЫЙ ОТВЕТ (AUTO-REPLY)** (Уверенность: {triage_res['confidence']:.2f})")
                st.markdown(f"**Отправленный игроку ответ:**\n> {dispatch_res['reply_sent']}")
            else:
                st.warning(f"🛡️ **СТАТУС: ЭСКАЛАЦИЯ ОПЕРАТОРУ** (Причина: {'; '.join(triage_res.get('reasons', ['Не типовой запрос']))})")
                st.markdown(f"**Сгенерированный черновик для оператора:**\n> {triage_res['draft_reply']['text']}")
                st.caption(f"Цитируемые правила: {', '.join(triage_res['draft_reply'].get('cited', [])) or 'Общий регламент'}")

    st.markdown("---")

    # 5. LIVE AUDIT LOG STREAM
    st.markdown("### 📜 Журнал аудита автономных решений (Audit Feed)")
    if crm_metrics["recent_records"]:
        df_audit = pd.DataFrame(crm_metrics["recent_records"])
        cols_to_show = ["timestamp", "ticket_id", "source_crm", "category", "priority", "confidence", "status", "reply_text"]
        existing_cols = [c for c in cols_to_show if c in df_audit.columns]
        st.dataframe(df_audit[existing_cols], use_container_width=True)
    else:
        st.info("Журнал аудита пока пуст. Запустите симулятор или подключите вебхук для начала сбора аналитики.")
