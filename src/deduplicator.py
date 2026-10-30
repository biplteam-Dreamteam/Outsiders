import datetime
from collections import defaultdict
from typing import Any

from rapidfuzz import fuzz


class TicketDeduplicator:
    """
    БОНУС №1: Модуль дедупликации и анти-спама.
    Отслеживает скользящее окно в 1 час (3600 секунд) по reporter_hash.
    Критерии спама / дубликата:
    1. >= 5 тикетов от одного игрока за 1 час.
    2. Текстовое сходство (RapidFuzz ratio > 85%) с недавним тикетом того же заявителя в окне 1 часа.
    """

    def __init__(
        self,
        time_window_seconds: int = 3600,
        max_tickets_per_hour: int = 5,
        similarity_threshold: float = 85.0,
    ):
        self.time_window_seconds = time_window_seconds
        self.max_tickets_per_hour = max_tickets_per_hour
        self.similarity_threshold = similarity_threshold
        # Key: reporter_hash -> list of dicts: {"ts": datetime, "text": str, "ticket_id": str}
        self.history: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def parse_timestamp(self, ts_raw: Any) -> datetime.datetime:
        if isinstance(ts_raw, datetime.datetime):
            return ts_raw
        if isinstance(ts_raw, str):
            try:
                # Handle ISO strings like 2026-03-14T19:02:00 or with Z
                return datetime.datetime.fromisoformat(ts_raw.replace("Z", ""))
            except Exception:
                pass
        return datetime.datetime.now()

    def check_and_update(self, ticket: dict[str, Any], text: str) -> bool:
        """
        Проверяет обращение на дубликат / спам и обновляет скользящую историю.
        Возвращает is_spam_or_duplicate (True/False).
        """
        reporter = ticket.get("reporter_hash")
        if not reporter:
            # If no reporter hash, cannot correlate
            return False

        current_ts = self.parse_timestamp(ticket.get("created_at"))
        cutoff_ts = current_ts - datetime.timedelta(seconds=self.time_window_seconds)

        # Clean history older than cutoff for this reporter
        user_history = self.history[reporter]
        valid_history = [item for item in user_history if item["ts"] >= cutoff_ts]

        is_spam_or_duplicate = False

        # Check 1: Flood / spam threshold (>= 5 tickets in 1 hour)
        if len(valid_history) >= self.max_tickets_per_hour:
            is_spam_or_duplicate = True

        # Check 2: Semantic / textual duplication with RapidFuzz
        clean_text = text.strip().lower()
        if not is_spam_or_duplicate and clean_text:
            for prev in valid_history:
                prev_text = prev["text"].strip().lower()
                if not prev_text:
                    continue
                # Exact or highly similar
                if clean_text == prev_text:
                    is_spam_or_duplicate = True
                    break
                sim = fuzz.token_sort_ratio(clean_text, prev_text)
                if sim >= self.similarity_threshold:
                    is_spam_or_duplicate = True
                    break

        # Record current ticket into history
        valid_history.append(
            {"ts": current_ts, "text": text, "ticket_id": ticket.get("ticket_id")}
        )
        self.history[reporter] = valid_history

        return is_spam_or_duplicate

    def reset(self):
        """Сброс истории (для тестов или перезапуска)"""
        self.history.clear()
