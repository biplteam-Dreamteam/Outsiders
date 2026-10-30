from typing import Any

from src.classifier import TicketClassifier
from src.deduplicator import TicketDeduplicator
from src.guardrails import check_guardrails, sanitize_draft
from src.llm_client import LLMClient
from src.preprocessor import detect_language, extract_facts, normalize_cp1251_kz
from src.rag_engine import RAGEngine


class SupportCopilotPipeline:
    """
    Полный сквозной пайплайн триажа:
    - Нормализация кодировки cp1251 (kz-буквы)
    - Определение языка (ru, kk, uz, en, und)
    - Извлечение фактов (ник, правила, пруфы, сервер)
    - Анти-спам и дедупликация (окно 1 час)
    - Классификация категории и приоритета (ML < 2 мс)
    - Guardrails безопасности
    - RAG по rules.json
    - Генерация черновика ответа с цитированием
    - Пост-санитайзинг от галлюцинаций правил
    """

    def __init__(self, rules_path: str = "rules.json", model_path: str | None = None):
        self.classifier = TicketClassifier(model_path)
        self.rag = RAGEngine(rules_path)
        self.llm = LLMClient()
        self.deduplicator = TicketDeduplicator()

    async def triage_ticket_async(self, ticket: dict[str, Any]) -> dict[str, Any]:
        """Асинхронная обработка одного тикета (с попыткой LLM)"""
        # 1. Text & Preprocessing
        player_msgs = [
            m.get("text", "")
            for m in ticket.get("messages", [])
            if m.get("role") == "player"
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
        if cls_res["low_confidence_needs_human"]:
            needs_human = True
            reasons.append("Низкая уверенность классификатора (confidence < 0.55)")
        if is_spam:
            reasons.append("Обнаружен спам или дубликат обращения")

        # 7. RAG Engine
        rules = self.rag.retrieve(
            clean_text + " " + str(ticket.get("rule_refs_raw", "") or ""),
            category=category,
            extracted_refs=extracted["rule_refs"],
            top_k=4,
        )

        # 8. Draft reply generation (LLM with instant Fallback)
        draft_raw = await self.llm.generate_draft(
            lang=lang,
            ticket=ticket,
            category=category,
            retrieved_rules=rules,
            nickname=extracted["nickname"],
        )

        # 9. Sanitize draft (Anti-hallucination filter)
        clean_draft_text, clean_cited = sanitize_draft(
            draft_raw["text"], draft_raw["cited"], self.rag.get_valid_rules_dict()
        )

        return {
            "lang": lang,
            "category": category,
            "priority": priority,
            "is_spam_or_duplicate": is_spam,
            "extracted": extracted,
            "draft_reply": {
                "lang": draft_raw.get("lang", lang),
                "text": clean_draft_text,
                "cited": clean_cited,
            },
            "needs_human": needs_human,
            "confidence": confidence,
            "reasons": sorted(list(set(reasons))),
        }

    def triage_ticket_sync(self, ticket: dict[str, Any]) -> dict[str, Any]:
        """Синхронная ультра-быстрая обработка (для пакетного инференса < 5 мс)"""
        # 1. Text & Preprocessing
        player_msgs = [
            m.get("text", "")
            for m in ticket.get("messages", [])
            if m.get("role") == "player"
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
        if cls_res["low_confidence_needs_human"]:
            needs_human = True
            reasons.append("Низкая уверенность классификатора (confidence < 0.55)")
        if is_spam:
            reasons.append("Обнаружен спам или дубликат обращения")

        # 7. RAG Engine
        rules = self.rag.retrieve(
            clean_text + " " + str(ticket.get("rule_refs_raw", "") or ""),
            category=category,
            extracted_refs=extracted["rule_refs"],
            top_k=4,
        )

        # 8. Draft reply generation (Instant Fallback generator)
        draft_raw = self.llm.generate_fallback(
            lang=lang,
            ticket=ticket,
            category=category,
            retrieved_rules=rules,
            nickname=extracted["nickname"],
        )

        # 9. Sanitize draft (Anti-hallucination filter)
        clean_draft_text, clean_cited = sanitize_draft(
            draft_raw["text"], draft_raw["cited"], self.rag.get_valid_rules_dict()
        )

        return {
            "lang": lang,
            "category": category,
            "priority": priority,
            "is_spam_or_duplicate": is_spam,
            "extracted": extracted,
            "draft_reply": {
                "lang": draft_raw.get("lang", lang),
                "text": clean_draft_text,
                "cited": clean_cited,
            },
            "needs_human": needs_human,
            "confidence": confidence,
            "reasons": sorted(list(set(reasons))),
        }
