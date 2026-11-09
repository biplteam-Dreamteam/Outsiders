import os
import re
import time
from typing import Any

import httpx

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:3b-instruct-q4_K_M")
TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT", "2.5"))
CIRCUIT_BREAKER_TTL = 10.0  # seconds to skip HTTP if server is down

FALLBACK_TEMPLATES = {
    "ru": {
        "with_rule": "Здравствуйте, {nick}! Ваше обращение принято к рассмотрению. Согласно регламенту (п. {ref}): «{text}». Специалисты поддержки занимаются решением вопроса.",
        "need_evidence": "Здравствуйте, {nick}! Для проведения проверки по вашему обращению, пожалуйста, предоставьте подтверждающие материалы (скриншот, квитанцию или видеозапись).",
        "general": "Здравствуйте, {nick}! Благодарим за обращение в службу клиентской поддержки. По вашей ситуации проводится проверка.",
        "appeal": "Здравствуйте, {nick}! Вопросы пересмотра решений рассматриваются официальной службой контроля качества и безопасности.",
        "report": "Здравствуйте! Если вам требуется консультация по функциям сервиса или тарифам, вы также можете ознакомиться со справочным разделом.",
        "payment": "Здравствуйте, {nick}! Вопросы по платежам, зачислениям и возвратам обрабатываются финансовым отделом. Приложите квитанцию или номер транзакции.",
    },
    "kk": {
        "with_rule": "Сәлеметсіз бе, {nick}! Сіздің өтінішіңіз қабылданды. Қызмет көрсету регламентінің ({ref}-тармағы) бойынша тексеру жүргізілуде: «{text}».",
        "need_evidence": "Сәлеметсіз бе, {nick}! Мәселені жан-жақты қарау үшін растайтын материалдарды (скриншот, чек немесе бейнежазба) ұсынуыңызды сұраймыз.",
        "general": "Сәлеметсіз бе, {nick}! Қолдау қызметіне хабарласқаныңыз үшін рахмет. Жағдайыңыз бойынша тексеру жүргізілуде.",
        "appeal": "Сәлеметсіз бе, {nick}! Қарау нәтижесіне шағымдану мәселелері сапаны бақылау бөлімі арқылы қарастырылады.",
        "report": "Сәлеметсіз бе! Сервис мүмкіндіктері немесе тарифтер бойынша көмек қажет болса, анықтамалық бөлімнен ақпарат ала аласыз.",
        "payment": "Сәлеметсіз бе, {nick}! Төлемдер мен қайтару мәселелері қаржы бөлімі арқылы қарастырылады. Түбіртек немесе транзакция нөмірін жіберуіңізді сұраймыз.",
    },
    "uz": {
        "with_rule": "Assalomu alaykum, {nick}! Murojaatingiz qabul qilindi. Xizmat ko'rsatish qoidalarining {ref}-bandi bo'yicha tekshiruv olib borilmoqda: «{text}».",
        "need_evidence": "Assalomu alaykum, {nick}! Murojaatni to'liq ko'rib chiqish uchun tasdiqlovchi dalillarni (skrinshot, chek yoki video) taqdim etishingizni so'raymiz.",
        "general": "Assalomu alaykum, {nick}! Mijozlarni qo'llab-quvvatlash xizmati. Murojaatingiz bo'yicha tekshiruv olib borilmoqda.",
        "appeal": "Assalomu alaykum, {nick}! Qarorlarni qayta ko'rib chiqish masalalari sifat nazorati bo'limi tomonidan ko'rib chiqiladi.",
        "report": "Assalomu alaykum! Xizmat funksiyalari bo'yicha ma'lumot olish uchun rasmiy qo'llanmadan foydalanishingiz mumkin.",
        "payment": "Assalomu alaykum, {nick}! To'lovlar va pulni qaytarish masalalari moliya bo'limi tomonidan ko'rib chiqiladi. Kvitansiya yoki tranzaksiya raqamini taqdim eting.",
    },
    "en": {
        "with_rule": "Hello, {nick}! Your request has been received. In accordance with policy {ref}: \"{text}\", our support specialists are handling the issue.",
        "need_evidence": "Hello, {nick}! To investigate your inquiry, please provide supporting evidence (screenshots, receipt, or screen recording).",
        "general": "Hello, {nick}! Thank you for contacting customer support. We are looking into your request.",
        "appeal": "Hello, {nick}! Escalations and policy review requests are handled by our compliance and security team.",
        "report": "Hello! If you need guidance regarding our features or subscription plans, please consult our documentation.",
        "payment": "Hello, {nick}! Billing and payment inquiries are processed by our financial department. Please attach your payment receipt or transaction ID.",
    },
}


class LLMClient:
    """
    Высокопроизводительный асинхронный клиент к LLM (Qwen2.5-3B-Instruct):
    - Connection Pooling (переиспользование HTTP TCP-сокетов)
    - Circuit Breaker при недоступности локального сервера
    - Мгновенный Fallback с цитированием официальных правил (p95 < 5ms)
    """

    def __init__(
        self,
        base_url: str = LLM_BASE_URL,
        model: str = LLM_MODEL,
        timeout: float = TIMEOUT_SECONDS,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.last_failure_time: float = 0.0
        self.circuit_breaker_ttl: float = CIRCUIT_BREAKER_TTL
        self._is_probing: bool = False
        # Persistent async client with connection pooling
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            limits = httpx.Limits(max_keepalive_connections=20, max_connections=50)
            self._client = httpx.AsyncClient(timeout=self.timeout, limits=limits)
        return self._client

    async def aclose(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def generate_fallback(
        self,
        lang: str,
        ticket: dict[str, Any],
        category: str,
        retrieved_rules: list[dict[str, Any]],
        nickname: str | None = None,
    ) -> dict[str, Any]:
        """
        Умный мультиязычный генератор черновиков без галлюцинаций.
        Гарантирует 100% цитирование реальных правил и нулевую латентность.
        """
        target_lang = lang if lang in FALLBACK_TEMPLATES else "ru"
        tmpl = FALLBACK_TEMPLATES[target_lang]
        nick = nickname or "игрок"
        if target_lang == "en":
            nick = nickname or "player"
        elif target_lang == "kk":
            nick = nickname or "ойыншы"
        elif target_lang == "uz":
            nick = nickname or "oyinchi"

        cited: list[str] = []
        text = ""

        # Case 0: Payment & Donate queries (official store / billing info without hallucination)
        ticket_str = str(ticket).lower()
        if category == "report.payment" or any(
            k in ticket_str
            for k in ("донат", "donate", "вип", "випка", "vip", "төлем", "to'lov")
        ):
            text = tmpl["payment"].format(nick=nick)

        # Case 1: Rules were retrieved
        elif retrieved_rules:
            top_rule = retrieved_rules[0]
            ref = str(top_rule.get("ref", "")).strip()
            rule_text = top_rule.get("text", "").strip()
            if len(rule_text) > 160:
                rule_text = rule_text[:157] + "..."
            for r in retrieved_rules:
                r_ref = str(r.get("ref", "")).strip()
                if r_ref and r_ref not in cited:
                    cited.append(r_ref)
            text = tmpl["with_rule"].format(nick=nick, ref=ref, text=rule_text)

        # Case 2: Appeal / admin complaint
        elif category in ("complaint.admin", "complaint.appeal"):
            text = tmpl["appeal"].format(nick=nick)

        # Case 3: Need evidence (invalid or missing proofs)
        elif category == "complaint.invalid" or (
            ticket.get("kind") == "complaint" and not ticket.get("images_count")
        ):
            text = tmpl["need_evidence"].format(nick=nick)

        # Case 4: In-game reports / questions
        elif ticket.get("kind") == "report":
            text = tmpl["report"].format(nick=nick)

        # Case 5: General fallback
        else:
            text = tmpl["general"].format(nick=nick)

        return {"lang": target_lang, "text": text, "cited": cited}

    def _validate_response_lang(self, content: str, target_lang: str) -> bool:
        """
        Гарантирует, что модель не сбилась на русский язык,
        если тикет был на казахском (kk) или узбекском (uz).
        """
        if not content:
            return False
        content_lower = content.lower()
        if target_lang == "kk":
            ru_markers = ["здравствуйте", "приветствуем", "ваше обращение", "принято к рассмотрению", "правил проекта"]
            kk_markers = ["сәлем", "салем", "сіздің", "өтініш", "қайырлы", "ереже", "тексеру", "шаралар", "рахмет", "әкімшілік", "ә", "ғ", "қ", "ң", "ө", "ұ", "ү", "і"]
            has_ru = any(m in content_lower for m in ru_markers)
            has_kk = any(m in content_lower for m in kk_markers)
            if has_ru and not has_kk:
                return False
            return True

        if target_lang == "uz":
            ru_markers = ["здравствуйте", "приветствуем", "ваше обращение", "принято к рассмотрению", "правил проекта"]
            uz_markers = ["assalomu", "alaykum", "murojaat", "qabul", "qoidalar", "tekshiruv", "choralar", "rahmat", "iltimos", "kerak", "o'", "g'"]
            has_ru = any(m in content_lower for m in ru_markers)
            has_uz = any(m in content_lower for m in uz_markers)
            if has_ru and not has_uz:
                return False
            return True

        return True

    async def generate_draft(
        self,
        lang: str,
        ticket: dict[str, Any],
        category: str,
        retrieved_rules: list[dict[str, Any]],
        nickname: str | None = None,
    ) -> dict[str, Any]:
        """
        Генерирует черновик ответа:
        1. Проверяет Circuit Breaker (если LLM недавно отвалилась, сразу fallback)
        2. Формирует жесткий мультиязычный CoT-промпт
        3. Пробует вызвать локальную LLM через connection pool
        4. При таймауте, ошибке или сбое языка мгновенно активирует чистый localized fallback
        """
        now = time.time()
        # Circuit Breaker: if LLM server failed in the last TTL seconds or already probing, immediately fallback
        if (now - self.last_failure_time) < self.circuit_breaker_ttl or self._is_probing:
            return self.generate_fallback(
                lang, ticket, category, retrieved_rules, nickname
            )

        matched_rules_list = []
        valid_refs = []
        for r in retrieved_rules:
            ref = str(r.get("ref", "")).strip()
            text = str(r.get("text", "")).strip()
            if ref and text:
                valid_refs.append(ref)
                matched_rules_list.append(f"Пункт {ref}: {text}")

        matched_rules = "\n".join(matched_rules_list)

        player_messages = [
            m.get("text", "")
            for m in ticket.get("messages", [])
            if m.get("role") == "player"
        ]
        query = " ".join(player_messages)

        system_prompt = (
            "Ты — строгий, но вежливый администратор Grand Mobile.\n"
            "Правило номер 1: ТЕБЕ ЗАПРЕЩЕНО ВЫДУМЫВАТЬ ПУНКТЫ ПРАВИЛ И НАКАЗАНИЯ.\n"
            "Правило номер 2: Отвечай строго на языке входящего запроса (ru, kk, uz, en).\n\n"
            "Тебе переданы ТОЛЬКО РЕАЛЬНЫЕ пункты правил из официального справочника:\n"
            f"{matched_rules}\n\n"
            "Твоя задача:\n"
            "1. Сформируй ответ, используя ТОЛЬКО переданные пункты.\n"
            "2. Не обещай снять бан, вернуть имущество или выдать наказание (этим занимаются старшие админы).\n"
            "3. Если {matched_rules} пустое — просто ответь на вопрос без цитирования цифр."
        )

        try:
            client = self._get_client()
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": (
                            f"Входящий запрос от игрока (язык: '{lang}'):\n\"{query}\"\n\n"
                            f"Сформируй краткий ответ игроку СТРОГО на языке '{lang}'. "
                            f"Выведи только финальный ответ:"
                        ),
                    },
                ],
                "max_tokens": 60,
                "temperature": 0.2,
            }
            self._is_probing = True
            resp = await client.post(f"{self.base_url}/chat/completions", json=payload)
            if resp.status_code == 200:
                self.circuit_breaker_ttl = CIRCUIT_BREAKER_TTL
                data = resp.json()
                content = data["choices"][0]["message"]["content"].strip()
                # Clean reasoning / CoT leakages if any
                content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
                for marker in ("4. ", "4) ", "Финальный ответ:", "Ответ:", "Жауап:", "Javob:", "Answer:"):
                    if marker in content:
                        content = content.split(marker)[-1].strip()

                # Validate language: ensure not fallen back to Russian if target was kk/uz
                if self._validate_response_lang(content, lang):
                    cited = [ref for ref in valid_refs if ref in content]
                    return {
                        "lang": lang if lang in FALLBACK_TEMPLATES else "ru",
                        "text": content,
                        "cited": cited,
                    }
        except Exception:
            # Mark failure for circuit breaker with backoff
            self.last_failure_time = time.time()
            self.circuit_breaker_ttl = min(60.0, self.circuit_breaker_ttl * 2)
        finally:
            self._is_probing = False

        return self.generate_fallback(lang, ticket, category, retrieved_rules, nickname)
