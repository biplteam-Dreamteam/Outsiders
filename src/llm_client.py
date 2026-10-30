import os
import json
import httpx
from typing import Dict, Any, List, Optional, Tuple

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:3b-instruct")
TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT", "3.0"))


FALLBACK_TEMPLATES = {
    "ru": {
        "with_rule": "Приветствуем, {nick}. Ваше обращение принято к рассмотрению. Ознакомьтесь с пунктом {ref} правил проекта: «{text}». Администрация сервера примет необходимые меры.",
        "need_evidence": "Приветствуем, {nick}. Для проведения проверки по вашей жалобе необходимо предоставить доказательства (скриншот или видеозапись с /time).",
        "general": "Здравствуйте, {nick}! Благодарим за обращение в поддержку Grand Mobile. По вашей ситуации проводится проверка.",
        "appeal": "Приветствуем, {nick}. Вопросы обжалования наказаний рассматриваются администрацией через официальный раздел апелляций.",
        "report": "Приветствуем! Если вам требуется помощь по командам или навигации, используйте /help и /gps в игре."
    },
    "kk": {
        "with_rule": "Сәлеметсіз бе, {nick}. Сіздің өтінішіңіз қабылданды. Жоба ережелерінің {ref} тармағымен танысыңыз: «{text}». Сервер әкімшілігі тиісті шаралар қабылдайды.",
        "need_evidence": "Сәлеметсіз бе, {nick}. Шағымды тексеру үшін дәлелдемелер (скриншот немесе /time бар бейнежазба) ұсыну қажет.",
        "general": "Сәлеметсіз бе, {nick}! Grand Mobile қолдау қызметіне хабарласқаныңыз үшін рахмет. Жағдайыңыз бойынша тексеру жүргізілуде.",
        "appeal": "Сәлеметсіз бе, {nick}. Жазаға шағымдану мәселелері ресми апелляция бөлімі арқылы қарастырылады.",
        "report": "Сәлеметсіз бе! Командалар мен бағдар бойынша көмек қажет болса, ойында /help және /gps пайдаланыңыз."
    },
    "uz": {
        "with_rule": "Assalomu alaykum, {nick}. Murojaatingiz qabul qilindi. Loyiha qoidalarining {ref}-bandi bilan tanishib chiqing: «{text}». Ma'muriyat tegishli choralarni ko'radi.",
        "need_evidence": "Assalomu alaykum, {nick}. Shikoyatni ko'rib chiqish uchun dalillar (skrinshot yoki /time bilan video) taqdim etishingiz kerak.",
        "general": "Assalomu alaykum, {nick}! Grand Mobile qo'llab-quvvatlash xizmati. Murojaatingiz bo'yicha tekshiruv olib borilmoqda.",
        "appeal": "Assalomu alaykum, {nick}. Jazoni bekor qilish masalalari ma'muriyatning rasmiy apellyatsiya bo'limida ko'rib chiqiladi.",
        "report": "Assalomu alaykum! Agar yordam kerak bo'lsa, o'yinda /help va /gps buyruqlaridan foydalanishingiz mumkin."
    },
    "en": {
        "with_rule": "Greetings, {nick}. Your request has been received. Please refer to rule {ref}: '{text}'. Server administration will take appropriate action.",
        "need_evidence": "Greetings, {nick}. To investigate your complaint, please provide valid evidence (screenshots or video with /time).",
        "general": "Hello, {nick}! Thank you for contacting Grand Mobile support. We are looking into your situation.",
        "appeal": "Greetings, {nick}. Penalty appeals must be submitted to the official appeal section.",
        "report": "Hello! For help with commands and navigation, please use /help and /gps in-game."
    }
}


class LLMClient:
    """
    Асинхронный клиент к LLM (Qwen2.5-3B-Instruct) с таймаутом 3.0 сек
    и отказоустойчивым мультиязычным Fallback-генератором.
    """
    def __init__(self, base_url: str = LLM_BASE_URL, model: str = LLM_MODEL, timeout: float = TIMEOUT_SECONDS):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def generate_fallback(
        self,
        lang: str,
        ticket: Dict[str, Any],
        category: str,
        retrieved_rules: List[Dict[str, Any]],
        nickname: Optional[str] = None
    ) -> Dict[str, Any]:
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

        cited: List[str] = []
        text = ""

        # Case 1: Rules were retrieved
        if retrieved_rules:
            top_rule = retrieved_rules[0]
            ref = str(top_rule.get("ref", "")).strip()
            rule_text = top_rule.get("text", "").strip()
            # Truncate text if too long
            if len(rule_text) > 160:
                rule_text = rule_text[:157] + "..."
            cited.append(ref)
            text = tmpl["with_rule"].format(nick=nick, ref=ref, text=rule_text)

        # Case 2: Appeal / admin complaint
        elif category in ("complaint.admin", "complaint.appeal"):
            text = tmpl["appeal"].format(nick=nick)

        # Case 3: Need evidence (invalid or missing proofs)
        elif category == "complaint.invalid" or (ticket.get("kind") == "complaint" and not ticket.get("images_count")):
            text = tmpl["need_evidence"].format(nick=nick)

        # Case 4: In-game reports / questions
        elif ticket.get("kind") == "report":
            text = tmpl["report"].format(nick=nick)

        # Case 5: General fallback
        else:
            text = tmpl["general"].format(nick=nick)

        return {
            "lang": target_lang,
            "text": text,
            "cited": cited
        }

    async def generate_draft(
        self,
        lang: str,
        ticket: Dict[str, Any],
        category: str,
        retrieved_rules: List[Dict[str, Any]],
        nickname: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Генерирует черновик ответа:
        1. Пробует вызвать локальную LLM (Qwen2.5-3B-Instruct) через OpenAI API
        2. При таймауте (3.0 сек) или недоступности использует мгновенный Fallback.
        """
        # Build prompt
        rules_context = ""
        valid_refs = []
        for r in retrieved_rules:
            ref = str(r.get("ref", "")).strip()
            valid_refs.append(ref)
            rules_context += f"Пункт {ref}: {r.get('text', '')}\n"

        player_messages = [m.get("text", "") for m in ticket.get("messages", []) if m.get("role") == "player"]
        query = " ".join(player_messages)

        system_prompt = (
            f"Ты — официальный ассистент поддержки Grand Mobile. "
            f"Ответь строго на языке пользователя: {lang}. "
            f"Будь вежлив, краток (не более 2-3 предложений). "
            f"Опирайся ТОЛЬКО на следующие пункты правил игры: \n{rules_context}\n"
            f"КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО выдумывать несуществующие правила или обещать разбан, возврат средств или наказание. "
            f"Разрешенные для цитирования пункты: {valid_refs}."
        )

        user_content = f"Игрок ({nickname or 'Игрок'}): {query}"

        # Attempt LLM call with strict timeout
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                payload = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content}
                    ],
                    "max_tokens": 150,
                    "temperature": 0.2
                }
                resp = await client.post(f"{self.base_url}/chat/completions", json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"].strip()
                    # Extract cited rules strictly from valid_refs
                    cited = [ref for ref in valid_refs if ref in content]
                    return {
                        "lang": lang if lang in FALLBACK_TEMPLATES else "ru",
                        "text": content,
                        "cited": cited
                    }
        except Exception:
            # Fallback seamlessly on any error or timeout
            pass

        # Use bulletproof fallback generator
        return self.generate_fallback(lang, ticket, category, retrieved_rules, nickname)
