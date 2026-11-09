import json
import os
from typing import Any

from src.classifier import TicketClassifier
from src.deduplicator import TicketDeduplicator
from src.guardrails import check_guardrails, sanitize_draft
from src.llm_client import LLMClient
from src.preprocessor import detect_language, extract_facts, normalize_cp1251_kz
from src.rag_engine import RAGEngine

CONFIG_PATH_DEFAULT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "admin_config.json"
)

DEFAULT_CONFIG: dict[str, Any] = {
    "operating_mode": "full",  # "full" (auto/draft), "triage_only" (classification only), "copilot_only" (human review)
    "cpu_threads": 8,
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


def load_pipeline_config(config_path: str = CONFIG_PATH_DEFAULT) -> dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if isinstance(saved, dict):
                    cfg.update(saved)
        except Exception:
            pass
    return cfg


class SupportCopilotPipeline:
    """
    Полный сквозной пайплайн триажа:
    - Нормализация кодировки cp1251 (kz-буквы)
    - Определение языка (ru, kk, uz, en, und)
    - Извлечение фактов (ник, правила, пруфы, сервер)
    - Анти-спам и дедупликация (окно 1 час)
    - Классификация категории и приоритета (ML < 2 мс)
    - Guardrails безопасности и управление режимами (Full vs Triage Only vs Copilot)
    - Динамическое регулирование потоков процессора (CPU threads) и памяти
    - RAG по rules.json (при operating_mode != 'triage_only')
    - Генерация черновика ответа с цитированием
    - Пост-санитайзинг от галлюцинаций правил
    """

    def __init__(
        self,
        rules_path: str = "rules.json",
        model_path: str | None = None,
        config_path: str = CONFIG_PATH_DEFAULT,
    ):
        self.config_path = config_path
        self.config = load_pipeline_config(config_path)
        self.operating_mode = self.config.get("operating_mode", "full")
        self.cpu_threads = int(self.config.get("cpu_threads", 8))
        self.ram_limit_mb = int(self.config.get("ram_limit_mb", 2048))

        self.classifier = TicketClassifier(model_path, thread_count=self.cpu_threads)
        self.rag = RAGEngine(rules_path)
        self.llm = LLMClient()
        sim_val = float(self.config.get("dedup_similarity_threshold", 0.85))
        sim_pct = sim_val * 100.0 if sim_val <= 1.0 else sim_val
        self.deduplicator = TicketDeduplicator(
            max_tickets_per_hour=int(self.config.get("max_tickets_per_hour", 5)),
            similarity_threshold=sim_pct,
        )

    def reload_config(self) -> None:
        """Перезагружает конфигурацию из файла в рантайме без перезапуска процесса."""
        self.config = load_pipeline_config(self.config_path)
        self.operating_mode = self.config.get("operating_mode", "full")
        self.cpu_threads = int(self.config.get("cpu_threads", 8))
        self.ram_limit_mb = int(self.config.get("ram_limit_mb", 2048))
        if hasattr(self.classifier, "set_thread_count"):
            self.classifier.set_thread_count(self.cpu_threads)

    def set_operating_mode(self, mode: str) -> None:
        """Переключает режим работы: 'full', 'triage_only', 'copilot_only'."""
        if mode in ("full", "triage_only", "copilot_only"):
            self.operating_mode = mode
            self.config["operating_mode"] = mode

    async def triage_ticket_async(self, ticket: dict[str, Any]) -> dict[str, Any]:
        """Асинхронная обработка одного тикета (с попыткой LLM)"""
        if not isinstance(ticket, dict):
            ticket = {}

        # 1. Text & Preprocessing (Safe against null and bad types)
        raw_msgs = ticket.get("messages") or []
        if not isinstance(raw_msgs, list):
            raw_msgs = []
        player_msgs = [
            m.get("text", "")
            for m in raw_msgs
            if isinstance(m, dict) and m.get("role") == "player"
        ]
        raw_text = " ".join(player_msgs)
        clean_text = normalize_cp1251_kz(raw_text)

        # 2. Language detection
        lang = detect_language(
            clean_text, default_lang=ticket.get("lang") or ticket.get("server_lang")
        )

        # 3. Facts extraction
        extracted = extract_facts(
            ticket,
            text=clean_text,
            rule_refs_raw=ticket.get("rule_refs_raw"),
            images_count=ticket.get("images_count"),
        )

        # 4. Deduplication / anti-spam (Bonus 1)
        is_spam = self.deduplicator.check_and_update(ticket, clean_text)

        # 5. Classifier (Category & Priority)
        cls_res = self.classifier.predict(ticket, clean_text, extracted["has_evidence"])
        category = cls_res["category"]
        priority = cls_res["priority"]
        confidence = cls_res["confidence"]

        # 6. Guardrails
        needs_human, reasons = check_guardrails(
            ticket, clean_text, category, extracted["has_evidence"]
        )

        conf_thresh = float(self.config.get("confidence_threshold", 0.55))
        if confidence < conf_thresh:
            needs_human = True
            reasons.append(f"Низкая уверенность классификатора ({confidence:.2f} < {conf_thresh:.2f})")

        human_cats = set(
            self.config.get(
                "human_required_categories",
                ["report.account", "report.payment", "complaint.admin", "complaint.cheat"],
            )
        )
        if category in human_cats:
            needs_human = True
            reasons.append(f"Политика безопасности: категория '{category}' требует человека")

        if self.config.get("evidence_requires_human", True) and extracted["has_evidence"]:
            needs_human = True
            reasons.append("Прикреплены доказательства (скриншот/видео): требует человека")

        if is_spam:
            needs_human = True
            reasons.append("Обнаружен спам или дубликат обращения")

        # Strict Rule Hallucination Shield: Validate extracted rule_refs against rules.json
        valid_rules_set = self.rag.validator.get_valid_rules()
        valid_extracted_refs = []
        for r in extracted.get("rule_refs", []):
            if r in valid_rules_set:
                valid_extracted_refs.append(r)
            else:
                needs_human = True
                reasons.append(f"Указано несуществующее правило: {r}")
        extracted["rule_refs"] = valid_extracted_refs

        # REQ 1: Operating Mode Handling
        if self.operating_mode == "triage_only":
            # Чистая классификация: генерация текста ответа отключена
            draft_reply = {
                "lang": lang if lang in ("ru", "kk", "uz", "en") else "ru",
                "text": "",
                "cited": [],
            }
            if needs_human and not reasons:
                reasons.append("Обращение требует подтверждения администратора")
            return {
                "lang": lang,
                "category": category,
                "priority": priority,
                "is_spam_or_duplicate": is_spam,
                "extracted": extracted,
                "draft_reply": draft_reply,
                "needs_human": needs_human,
                "confidence": confidence,
                "reasons": sorted(list(set(reasons))),
            }

        if self.operating_mode == "copilot_only":
            needs_human = True
            reasons.append("Режим 'Ассистент модератора': требуется утверждение черновика оператором")

        # 7. RAG Engine
        rules = self.rag.retrieve(
            clean_text + " " + str(ticket.get("rule_refs_raw", "") or ""),
            category=category,
            extracted_refs=extracted["rule_refs"],
            top_k=4,
        )

        # 8. Draft reply generation (LLM with instant Fallback)
        draft_lang = lang if lang in ("ru", "kk", "uz", "en") else "ru"
        is_payment_query = category == "report.payment" or any(
            k in clean_text.lower() for k in ("донат", "donate", "вип", "випка", "vip", "төлем", "to'lov")
        )
        if is_payment_query:
            draft_raw = self.llm.generate_fallback(
                lang=draft_lang,
                ticket=ticket,
                category=category,
                retrieved_rules=[],
                nickname=extracted["nickname"],
            )
        else:
            draft_raw = await self.llm.generate_draft(
                lang=draft_lang,
                ticket=ticket,
                category=category,
                retrieved_rules=rules,
                nickname=extracted["nickname"],
            )

        # 9. Sanitize draft (Anti-hallucination filter)
        sanitized_draft = sanitize_draft(
            draft_raw, self.rag.validator.get_valid_rules()
        )
        if sanitized_draft.get("lang") not in ("ru", "kk", "uz", "en"):
            sanitized_draft["lang"] = draft_lang

        if needs_human and not reasons:
            reasons.append("Обращение требует подтверждения администратора")

        return {
            "lang": lang,
            "category": category,
            "priority": priority,
            "is_spam_or_duplicate": is_spam,
            "extracted": extracted,
            "draft_reply": sanitized_draft,
            "needs_human": needs_human,
            "confidence": confidence,
            "reasons": sorted(list(set(reasons))),
        }

    def triage_ticket_sync(self, ticket: dict[str, Any]) -> dict[str, Any]:
        """Синхронная ультра-быстрая обработка (для пакетного инференса < 5 мс)"""
        if not isinstance(ticket, dict):
            ticket = {}

        # 1. Text & Preprocessing (Safe against null and bad types)
        raw_msgs = ticket.get("messages") or []
        if not isinstance(raw_msgs, list):
            raw_msgs = []
        player_msgs = [
            m.get("text", "")
            for m in raw_msgs
            if isinstance(m, dict) and m.get("role") == "player"
        ]
        raw_text = " ".join(player_msgs)
        clean_text = normalize_cp1251_kz(raw_text)

        # 2. Language detection
        lang = detect_language(
            clean_text, default_lang=ticket.get("lang") or ticket.get("server_lang")
        )

        # 3. Facts extraction
        extracted = extract_facts(
            ticket,
            text=clean_text,
            rule_refs_raw=ticket.get("rule_refs_raw"),
            images_count=ticket.get("images_count"),
        )

        # 4. Deduplication / anti-spam (Bonus 1)
        is_spam = self.deduplicator.check_and_update(ticket, clean_text)

        # 5. Classifier (Category & Priority)
        cls_res = self.classifier.predict(ticket, clean_text, extracted["has_evidence"])
        category = cls_res["category"]
        priority = cls_res["priority"]
        confidence = cls_res["confidence"]

        # 6. Guardrails
        needs_human, reasons = check_guardrails(
            ticket, clean_text, category, extracted["has_evidence"]
        )

        conf_thresh = float(self.config.get("confidence_threshold", 0.55))
        if confidence < conf_thresh:
            needs_human = True
            reasons.append(f"Низкая уверенность классификатора ({confidence:.2f} < {conf_thresh:.2f})")

        human_cats = set(
            self.config.get(
                "human_required_categories",
                ["report.account", "report.payment", "complaint.admin", "complaint.cheat"],
            )
        )
        if category in human_cats:
            needs_human = True
            reasons.append(f"Политика безопасности: категория '{category}' требует человека")

        if self.config.get("evidence_requires_human", True) and extracted["has_evidence"]:
            needs_human = True
            reasons.append("Прикреплены доказательства (скриншот/видео): требует человека")

        if is_spam:
            needs_human = True
            reasons.append("Обнаружен спам или дубликат обращения")

        # Strict Rule Hallucination Shield: Validate extracted rule_refs against rules.json
        valid_rules_set = self.rag.validator.get_valid_rules()
        valid_extracted_refs = []
        for r in extracted.get("rule_refs", []):
            if r in valid_rules_set:
                valid_extracted_refs.append(r)
            else:
                needs_human = True
                reasons.append(f"Указано несуществующее правило: {r}")
        extracted["rule_refs"] = valid_extracted_refs

        # REQ 1: Operating Mode Handling
        if self.operating_mode == "triage_only":
            # Чистая классификация: генерация текста ответа отключена
            draft_reply = {
                "lang": lang if lang in ("ru", "kk", "uz", "en") else "ru",
                "text": "",
                "cited": [],
            }
            if needs_human and not reasons:
                reasons.append("Обращение требует подтверждения администратора")
            return {
                "lang": lang,
                "category": category,
                "priority": priority,
                "is_spam_or_duplicate": is_spam,
                "extracted": extracted,
                "draft_reply": draft_reply,
                "needs_human": needs_human,
                "confidence": confidence,
                "reasons": sorted(list(set(reasons))),
            }

        if self.operating_mode == "copilot_only":
            needs_human = True
            reasons.append("Режим 'Ассистент модератора': требуется утверждение черновика оператором")

        # 7. RAG Engine
        rules = self.rag.retrieve(
            clean_text + " " + str(ticket.get("rule_refs_raw", "") or ""),
            category=category,
            extracted_refs=extracted["rule_refs"],
            top_k=4,
        )

        # 8. Draft reply generation (Instant Fallback generator)
        draft_lang = lang if lang in ("ru", "kk", "uz", "en") else "ru"
        draft_raw = self.llm.generate_fallback(
            lang=draft_lang,
            ticket=ticket,
            category=category,
            retrieved_rules=rules,
            nickname=extracted["nickname"],
        )

        # 9. Sanitize draft (Anti-hallucination filter)
        sanitized_draft = sanitize_draft(
            draft_raw, self.rag.validator.get_valid_rules()
        )
        if sanitized_draft.get("lang") not in ("ru", "kk", "uz", "en"):
            sanitized_draft["lang"] = draft_lang

        if needs_human and not reasons:
            reasons.append("Обращение требует подтверждения администратора")

        return {
            "lang": lang,
            "category": category,
            "priority": priority,
            "is_spam_or_duplicate": is_spam,
            "extracted": extracted,
            "draft_reply": sanitized_draft,
            "needs_human": needs_human,
            "confidence": confidence,
            "reasons": sorted(list(set(reasons))),
        }


_DEFAULT_PIPELINE: SupportCopilotPipeline | None = None


def get_default_pipeline(rules_path: str = "rules.json") -> SupportCopilotPipeline:
    global _DEFAULT_PIPELINE
    if _DEFAULT_PIPELINE is None:
        _DEFAULT_PIPELINE = SupportCopilotPipeline(rules_path=rules_path)
    return _DEFAULT_PIPELINE
