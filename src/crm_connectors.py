import datetime
import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("via-crm-connectors")

AUDIT_LOG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "auto_reply_audit.jsonl"
)
CONFIG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "admin_config.json"
)


class CRMConnectorManager:
    """
    Промышленный диспетчер B2B-интеграций и автономного авто-ответчика:
    - Коннекторы: Zendesk, Telegram, amoCRM, Bitrix24, Generic Webhook
    - Преобразование входящих тикетов любой CRM к стандарту системы
    - Автоматическая отправка регламентных ответов игрокам (Auto-Reply)
    - Автоматическая публикация приватных заметок операторам при эскалации
    - Аудит и статистика автоматизации (Deflection Rate)
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or self.load_config()

    def load_config(self) -> dict[str, Any]:
        defaults = {
            "auto_reply_enabled": True,
            "min_confidence_auto_reply": 0.70,
            "allowed_auto_reply_categories": [
                "report.question",
                "report.help",
                "report.complaint",
                "report.offtopic",
                "complaint.invalid",
            ],
            "generic_webhook": {"enabled": True, "default_callback_url": ""},
            "telegram": {"enabled": False, "bot_token": "", "escalation_chat_id": ""},
            "zendesk": {"enabled": False, "subdomain": "", "email": "", "api_token": ""},
            "amocrm": {"enabled": False, "subdomain": "", "access_token": ""},
        }
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    saved = cfg.get("b2b_crm")
                    if isinstance(saved, dict) and saved:
                        defaults.update(saved)
            except Exception as e:
                logger.warning(f"Failed to load CRM config: {e}")
        return defaults

    def save_config(self, crm_cfg: dict[str, Any]) -> None:
        try:
            full_cfg = {}
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    full_cfg = json.load(f)
            full_cfg["b2b_crm"] = crm_cfg
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(full_cfg, f, ensure_ascii=False, indent=2)
            self.config = crm_cfg
        except Exception as e:
            logger.error(f"Failed to save CRM config: {e}")

    # =========================================================================
    # Входящие адаптеры тикетов (Inbound Adapters)
    # =========================================================================
    def adapt_inbound_ticket(self, crm_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Универсальная диспетчеризация входящих вебхуков по типу CRM."""
        crm_norm = (crm_type or "").lower().strip()
        if crm_norm in ("telegram", "tg"):
            adapted = self.adapt_telegram_update(payload)
            if adapted:
                return adapted
        elif crm_norm in ("zendesk", "zd"):
            return self.adapt_zendesk_ticket(payload)
        return self.adapt_generic_payload(payload)

    def adapt_generic_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Универсальный адаптер: принимает JSON любой структуры."""
        messages = payload.get("messages")
        if not messages:
            text = payload.get("text") or payload.get("message") or payload.get("body") or payload.get("description") or ""
            messages = [{"role": "player", "text": str(text)}]

        return {
            "ticket_id": str(payload.get("ticket_id") or payload.get("id") or f"crm_{int(datetime.datetime.now().timestamp()*1000)}"),
            "kind": payload.get("kind", "report"),
            "reporter_hash": payload.get("reporter_hash") or payload.get("user_id") or payload.get("customer_id") or payload.get("phone"),
            "reported_nick": payload.get("reported_nick") or payload.get("target_user"),
            "server_lang": payload.get("server_lang") or payload.get("lang"),
            "lang": payload.get("lang"),
            "images_count": int(payload.get("images_count") or payload.get("attachments_count") or len(payload.get("attachments") or []) or 0),
            "messages": messages,
            "callback_url": payload.get("callback_url") or payload.get("webhook_url") or self.config.get("generic_webhook", {}).get("default_callback_url"),
            "source_crm": payload.get("source_crm", "generic_webhook"),
            "crm_raw_meta": payload.get("metadata", {}),
        }

    def adapt_telegram_update(self, update: dict[str, Any]) -> dict[str, Any] | None:
        """Адаптер входящего вебхука Telegram Bot."""
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return None

        chat = msg.get("chat", {})
        chat_id = chat.get("id")
        user = msg.get("from", {})
        text = msg.get("text") or msg.get("caption") or ""
        photos = msg.get("photo", [])
        has_photo = len(photos) > 0 or "document" in msg

        return {
            "ticket_id": f"tg_{chat_id}_{msg.get('message_id')}",
            "kind": "report" if "жалоб" not in text.lower() else "complaint",
            "reporter_hash": f"tg_user_{user.get('id')}",
            "reported_nick": None,
            "server_lang": "ru",
            "lang": user.get("language_code") or "ru",
            "images_count": 1 if has_photo else 0,
            "messages": [{"role": "player", "text": text}],
            "callback_url": None,
            "source_crm": "telegram",
            "crm_raw_meta": {
                "chat_id": chat_id,
                "message_id": msg.get("message_id"),
                "username": user.get("username"),
                "first_name": user.get("first_name"),
            },
        }

    def adapt_zendesk_ticket(self, zendesk_payload: dict[str, Any]) -> dict[str, Any]:
        """Адаптер входящего тикета Zendesk (Webhooks / Trigger)."""
        ticket = zendesk_payload.get("ticket") or zendesk_payload
        ticket_id = str(ticket.get("id", "zd_temp"))
        subject = ticket.get("subject", "")
        description = ticket.get("description", "")
        full_text = f"{subject}\n{description}".strip()

        return {
            "ticket_id": f"zd_{ticket_id}",
            "kind": "complaint" if "жалоб" in full_text.lower() or "cheat" in full_text.lower() else "report",
            "reporter_hash": str(ticket.get("requester_id") or ticket.get("requester", {}).get("email") or "zd_user"),
            "reported_nick": None,
            "server_lang": "ru",
            "lang": None,
            "images_count": len(ticket.get("attachments") or []),
            "messages": [{"role": "player", "text": full_text}],
            "callback_url": None,
            "source_crm": "zendesk",
            "crm_raw_meta": {
                "zendesk_id": ticket_id,
                "external_id": ticket.get("external_id"),
                "tags": ticket.get("tags", []),
            },
        }

    # =========================================================================
    # Автономный диспетчер авто-ответов (Outbound Auto-Reply Dispatcher)
    # =========================================================================
    async def process_and_dispatch(
        self,
        ticket: dict[str, Any],
        triage_result: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Главная бизнес-логика автономного ответа:
        1. Проверяет Guardrails и политику авто-ответа компании.
        2. Если обращение типовое, уверенность высокая и модератор не требуется:
           -> Автоматически отправляет ответ в CRM / чат игрока.
        3. Если требуется человек:
           -> Отправляет приватную заметку / карточку эскалации оператору с черновиком.
        4. Фиксирует запись в аудит-журнале.
        """
        crm_cfg = self.config
        auto_reply_enabled = bool(crm_cfg.get("auto_reply_enabled", True))
        min_conf = float(crm_cfg.get("min_confidence_auto_reply", 0.70))
        allowed_cats = set(crm_cfg.get("allowed_auto_reply_categories", []))

        category = triage_result.get("category", "")
        confidence = float(triage_result.get("confidence", 0.0))
        needs_human = bool(triage_result.get("needs_human", True))
        draft = triage_result.get("draft_reply", {})
        reply_text = draft.get("text", "")
        source_crm = ticket.get("source_crm", "generic_webhook")
        ticket_id = ticket.get("ticket_id", "unknown")

        can_auto_reply = (
            auto_reply_enabled
            and not needs_human
            and confidence >= min_conf
            and (category in allowed_cats or len(allowed_cats) == 0)
            and len(reply_text.strip()) > 0
        )

        dispatch_status = "PENDING"
        dispatch_channel = source_crm
        delivery_error = None

        if can_auto_reply:
            # 🚀 СЛУЧАЙ 1: ПОЛНЫЙ АВТОПИЛОТ (AUTO-REPLY)
            success = await self._send_direct_reply(ticket, reply_text)
            if success:
                dispatch_status = "AUTO_REPLIED"
            else:
                dispatch_status = "AUTO_REPLY_FAILED"
                delivery_error = "Delivery failed to CRM endpoint"
        else:
            # 🛡️ СЛУЧАЙ 2: ЭСКАЛАЦИЯ ОПЕРАТОРУ (HUMAN-IN-THE-LOOP)
            success = await self._send_operator_escalation(ticket, triage_result)
            dispatch_status = "ESCALATED_TO_OPERATOR"

        # Запись в аудит-лог
        audit_record = {
            "timestamp": datetime.datetime.now().isoformat(),
            "ticket_id": ticket_id,
            "source_crm": source_crm,
            "category": category,
            "priority": triage_result.get("priority", "p3"),
            "confidence": round(confidence, 4),
            "needs_human": needs_human,
            "can_auto_reply": can_auto_reply,
            "status": dispatch_status,
            "reply_text": reply_text,
            "cited_rules": draft.get("cited", []),
            "reasons": triage_result.get("reasons", []),
            "error": delivery_error,
        }
        self._append_audit_log(audit_record)

        return {
            "ticket_id": ticket_id,
            "action": dispatch_status,
            "auto_replied": dispatch_status == "AUTO_REPLIED",
            "reply_sent": reply_text if dispatch_status == "AUTO_REPLIED" else None,
            "triage": triage_result,
            "audit_timestamp": audit_record["timestamp"],
        }

    # =========================================================================
    # Сетевые методы отправки (Outbound Transports)
    # =========================================================================
    async def _send_direct_reply(self, ticket: dict[str, Any], reply_text: str) -> bool:
        """Отправляет готовый регламентный ответ напрямую клиенту/игроку."""
        source = ticket.get("source_crm", "generic_webhook")

        # 1. Generic Webhook (Callback URL)
        callback_url = ticket.get("callback_url")
        if callback_url:
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    resp = await client.post(
                        callback_url,
                        json={
                            "event": "ticket.auto_replied",
                            "ticket_id": ticket.get("ticket_id"),
                            "status": "resolved",
                            "reply_text": reply_text,
                            "timestamp": datetime.datetime.now().isoformat(),
                        },
                    )
                    return resp.is_success
            except Exception as e:
                logger.warning(f"Failed to post auto-reply to callback_url ({callback_url}): {e}")

        # 2. Telegram Bot Direct Reply
        if source == "telegram":
            meta = ticket.get("crm_raw_meta", {})
            chat_id = meta.get("chat_id")
            token = self.config.get("telegram", {}).get("bot_token")
            if token and chat_id:
                try:
                    url = f"https://api.telegram.org/bot{token}/sendMessage"
                    async with httpx.AsyncClient(timeout=6.0) as client:
                        resp = await client.post(
                            url,
                            json={
                                "chat_id": chat_id,
                                "text": reply_text,
                                "reply_to_message_id": meta.get("message_id"),
                            },
                        )
                        return resp.is_success
                except Exception as e:
                    logger.warning(f"Telegram auto-reply error: {e}")

        # 3. Zendesk Public Comment
        if source == "zendesk":
            meta = ticket.get("crm_raw_meta", {})
            zd_id = meta.get("zendesk_id")
            zd_cfg = self.config.get("zendesk", {})
            subdomain = zd_cfg.get("subdomain")
            email = zd_cfg.get("email")
            token = zd_cfg.get("api_token")
            if subdomain and email and token and zd_id:
                try:
                    url = f"https://{subdomain}.zendesk.com/api/v2/tickets/{zd_id}.json"
                    auth = (f"{email}/token", token)
                    payload = {
                        "ticket": {
                            "comment": {"body": reply_text, "public": True},
                            "status": "solved",
                            "tags": meta.get("tags", []) + ["via-auto-replied"],
                        }
                    }
                    async with httpx.AsyncClient(timeout=8.0) as client:
                        resp = await client.put(url, json=payload, auth=auth)
                        return resp.is_success
                except Exception as e:
                    logger.warning(f"Zendesk auto-reply error: {e}")

        return True

    async def _send_operator_escalation(
        self, ticket: dict[str, Any], triage_result: dict[str, Any]
    ) -> bool:
        """Передает тикет операторам (приватный черновик в Zendesk или алерт в Telegram)."""
        source = ticket.get("source_crm", "generic_webhook")
        draft = triage_result.get("draft_reply", {})
        draft_text = draft.get("text", "")
        category = triage_result.get("category", "")
        prio = triage_result.get("priority", "p2")
        reasons_str = "; ".join(triage_result.get("reasons", []))

        # 1. Telegram Admin Alert Channel
        tg_cfg = self.config.get("telegram", {})
        escalation_chat_id = tg_cfg.get("escalation_chat_id")
        token = tg_cfg.get("bot_token")
        if token and escalation_chat_id:
            try:
                alert_text = (
                    f"⚠️ <b>ТРЕБУЕТСЯ ОПЕРАТОР [{prio.upper()}]</b>\n"
                    f"<b>Тикет:</b> <code>{ticket.get('ticket_id')}</code>\n"
                    f"<b>Категория:</b> <code>{category}</code>\n"
                    f"<b>Причина эскалации:</b> {reasons_str}\n\n"
                    f"<b>Текст обращения:</b>\n<i>{ticket.get('messages', [{}])[0].get('text', '')[:300]}</i>\n\n"
                    f"<b>💡 Предложенный черновик:</b>\n{draft_text}"
                )
                url = f"https://api.telegram.org/bot{token}/sendMessage"
                async with httpx.AsyncClient(timeout=6.0) as client:
                    await client.post(url, json={"chat_id": escalation_chat_id, "text": alert_text, "parse_mode": "HTML"})
            except Exception as e:
                logger.warning(f"Telegram escalation alert error: {e}")

        # 2. Zendesk Private Internal Note
        if source == "zendesk":
            meta = ticket.get("crm_raw_meta", {})
            zd_id = meta.get("zendesk_id")
            zd_cfg = self.config.get("zendesk", {})
            subdomain = zd_cfg.get("subdomain")
            email = zd_cfg.get("email")
            token = zd_cfg.get("api_token")
            if subdomain and email and token and zd_id:
                try:
                    url = f"https://{subdomain}.zendesk.com/api/v2/tickets/{zd_id}.json"
                    auth = (f"{email}/token", token)
                    internal_body = (
                        f"🛡️ [VIA AUTOMATION] Тикет требует внимания человека ({reasons_str}).\n"
                        f"Категория: {category} | Приоритет: {prio.upper()}\n\n"
                        f"💡 Рекомендованный черновик ответа:\n{draft_text}\n\n"
                        f"Использованные статьи правил: {', '.join(draft.get('cited', []))}"
                    )
                    payload = {
                        "ticket": {
                            "comment": {"body": internal_body, "public": False},
                            "priority": "urgent" if prio == "p0" else "high" if prio == "p1" else "normal",
                            "tags": meta.get("tags", []) + ["via-needs-human", f"prio-{prio}"],
                        }
                    }
                    async with httpx.AsyncClient(timeout=8.0) as client:
                        await client.put(url, json=payload, auth=auth)
                except Exception as e:
                    logger.warning(f"Zendesk internal note error: {e}")

        return True

    def _append_audit_log(self, record: dict[str, Any]) -> None:
        try:
            os.makedirs(os.path.dirname(AUDIT_LOG_FILE), exist_ok=True)
            with open(AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")

    # =========================================================================
    # Статистика и B2B Аналитика для Dashboard
    # =========================================================================
    def get_audit_metrics(self, max_records: int = 500) -> dict[str, Any]:
        """Возвращает агрегированные бизнес-метрики автоматизации."""
        records = []
        if os.path.exists(AUDIT_LOG_FILE):
            try:
                with open(AUDIT_LOG_FILE, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    for line in lines[-max_records:]:
                        line_str = line.strip()
                        if line_str:
                            records.append(json.loads(line_str))
            except Exception:
                pass

        total = len(records)
        auto_replied = sum(1 for r in records if r.get("status") == "AUTO_REPLIED")
        escalated = sum(1 for r in records if r.get("status") == "ESCALATED_TO_OPERATOR")
        failed = sum(1 for r in records if r.get("status") == "AUTO_REPLY_FAILED")

        deflection_rate = (auto_replied / total * 100.0) if total > 0 else 0.0
        # Экономия: в среднем 3 минуты оператора на регламентный тикет
        hours_saved = round((auto_replied * 3.0) / 60.0, 1)

        return {
            "total_tickets": total,
            "auto_replied": auto_replied,
            "escalated_to_operator": escalated,
            "delivery_failed": failed,
            "deflection_rate_pct": round(deflection_rate, 1),
            "operator_hours_saved": hours_saved,
            "recent_records": list(reversed(records[-50:])),
        }
