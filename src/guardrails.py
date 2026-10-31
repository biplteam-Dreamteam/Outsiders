import re
from typing import Any

HUMAN_REQUIRED_CATEGORIES = {"report.account", "report.payment", "complaint.admin"}

# Multilingual keywords for high-risk / human required topics
PAYMENT_KEYWORDS = {
    # ru
    "донат",
    "donate",
    "вип",
    "випка",
    "vip",
    "оплат",
    "платеж",
    "платёж",
    "гк",
    "деньги не пришли",
    "пополнил",
    "списали",
    "чеки",
    # kk
    "төлем",
    "толем",
    "ақша келмеді",
    "акша келмеди",
    "сатып алу",
    # uz
    "to'lov",
    "tolov",
    "pul tushmadi",
    "donat",
    "kartadan",
    "yechildi",
    # en
    "payment",
    "donation",
    "purchased",
    "not received",
    "money lost",
}

UNBAN_APPEAL_KEYWORDS = {
    # ru
    "разбан",
    "разбаньте",
    "unban",
    "ошибочный бан",
    "не согласен с наказанием",
    "снимите бан",
    "несправедливый бан",
    "разблокируйте",
    "апелляци",
    "обжалование",
    # kk
    "баннан шығар",
    "жазаны алып таста",
    "дұрыс емес бан",
    "шағымдану",
    # uz
    "blokdan chiqar",
    "noto'g'ri ban",
    "blok ochish",
    # en
    "appeal",
    "wrong ban",
    "unfair ban",
    "unblock",
}

HACK_KEYWORDS = {
    # ru
    "взлом",
    "взломали",
    "украли аккаунт",
    "сменили пароль",
    "потерял доступ",
    "кража аккаунта",
    # kk
    "аккаунт ұрланды",
    "пароль ауыстырды",
    "пароль ауыстырған",
    "қолжетімділік жоғалды",
    "ұрлап кетті",
    "ұрлап",
    "аккаунтымды",
    # uz
    "akkaunt buzildi",
    "parol o'zgardi",
    "og'irlandi",
    "profilim",
    # en
    "hacked",
    "stolen account",
    "lost access",
    "account stolen",
    "password changed",
}

PUNISHMENT_DECISION_KEYWORDS = {
    # ru
    "выдать бан",
    "накажите игрока",
    "забаньте его",
    "верните имущество",
    "верните деньги",
    "требую наказать",
    "компенсацию",
    "забанить",
    "деморган ему",
    "мут ему",
    # kk
    "жазалаңыз",
    "бандаңыз",
    "мүлікті қайтар",
    "ақшамды қайтар",
    # uz
    "jazolang",
    "ban bering",
    "pulimni qaytar",
    "mulkni qaytar",
    # en
    "ban him",
    "punish player",
    "return money",
    "return property",
}

FORBIDDEN_PROMISES = [
    # ru
    (
        re.compile(
            r"\b(?:мы\s+)?(?:разбаним|снимем\s+бан|разблокируем|снимем\s+наказание)\b",
            re.IGNORECASE,
        ),
        "вопрос о снятии наказания решается через раздел апелляций",
    ),
    (
        re.compile(
            r"\b(?:мы\s+)?(?:вернем|возместим|компенсируем)\s+(?:деньги|имущество|валюту)\b",
            re.IGNORECASE,
        ),
        "согласно регламенту имущество при мошенничестве или утере не восстанавливается",
    ),
    (
        re.compile(
            r"\b(?:игрок\s+)?(?:будет\s+наказан|получит\s+бан|получит\s+наказание)\b",
            re.IGNORECASE,
        ),
        "решение о мере наказания принимает администрация после рассмотрения доказательств",
    ),
    # kk
    (
        re.compile(
            r"\b(?:біз\s+)?(?:банды\s+аламыз|бұғаттан\s+шығарамыз)\b", re.IGNORECASE
        ),
        "жазаны алып тастау мәселесі шағымдар бөлімінде қаралады",
    ),
    # uz
    (
        re.compile(r"\b(?:blokdan\s+chiqaramiz|pulni\s+qaytaramiz)\b", re.IGNORECASE),
        "jazo va mulkni qaytarish ma'muriyat tomonidan ko'rib chiqiladi",
    ),
    # en
    (
        re.compile(
            r"\b(?:we\s+will\s+unban|will\s+return\s+your\s+money)\b", re.IGNORECASE
        ),
        "all sanction and refund matters are subject to official administrator review",
    ),
]


def check_guardrails(
    ticket: dict[str, Any], text: str, category: str, has_evidence: bool = False
) -> tuple[bool, list[str]]:
    """
    Проверяет жесткие критерии безопасности.
    Возвращает (needs_human, reasons).
    """
    needs_human = False
    reasons: list[str] = []
    text_lower = text.lower()

    # 1. Mandatory categories from taxonomy
    if category in HUMAN_REQUIRED_CATEGORIES:
        needs_human = True
        reasons.append(
            f"Категория '{category}' требует обязательного ручного разбора администратором"
        )

    # 2. Payment & Donates
    if any(k in text_lower for k in PAYMENT_KEYWORDS):
        needs_human = True
        reasons.append("Вопрос касается финансовых операций / доната / платежей")

    # 3. Account theft & Hacks
    if any(k in text_lower for k in HACK_KEYWORDS):
        needs_human = True
        reasons.append("Обращение связано со взломом или потерей доступа к аккаунту")

    # 4. Ban appeals
    if any(k in text_lower for k in UNBAN_APPEAL_KEYWORDS):
        needs_human = True
        reasons.append("Запрос на апелляцию блокировки или пересмотр наказания")

    # 5. Demands of punishment / refunds (Admin verdict required)
    if any(k in text_lower for k in PUNISHMENT_DECISION_KEYWORDS):
        needs_human = True
        reasons.append("Решение о наказании/возврате подтверждает администратор")

    # 6. Complaint with evidence demanding action
    if ticket.get("kind") == "complaint" and has_evidence:
        # Complaints with evidence require administrator decision to impose sanctions
        needs_human = True
        reasons.append(
            "Жалоба с доказательствами: решение о наказании выносит администратор"
        )

    return needs_human, sorted(list(set(reasons)))


SAFE_FALLBACK_TEXT = (
    "Здравствуйте. Ваше обращение передано профильным специалистам для проверки."
)
RULE_NUMBER_PATTERN = re.compile(r"\b(\d+\.\d+(?:\.\d+)?)\b")


def sanitize_draft(
    draft_reply: dict[str, Any] | str,
    valid_rules: set[str] | dict[str, Any] | list[str],
    legacy_rules: dict[str, Any] | set[str] | None = None,
) -> dict[str, Any] | tuple[str, list[str]]:
    r"""
    УРОВЕНЬ 3: Параноидальный Пост-Чекер (Paranoid Post-Checker)
    Логика:
    1. Исключает запрещенные обещания разбана / возврата средств.
    2. Проверяет draft_reply["cited"]: если элемента НЕТ в valid_rules, удаляет его из cited.
    3. Регулярным выражением r'\b\d+\.\d+(?:\.\d+)?\b' ищет в тексте draft_reply["text"] все упоминания чисел.
       Если найдено число, похожее на пункт правил, но его НЕТ в valid_rules, заменяет весь текст ответа
       на безопасную заглушку:
       "Здравствуйте. Ваше обращение передано профильным специалистам для проверки."
       и очищает cited от выдуманного.
    """
    # Legacy compatibility check: sanitize_draft(draft_text: str, cited: list, valid_rules_dict)
    if isinstance(draft_reply, str):
        text_input = draft_reply
        cited_input = valid_rules if isinstance(valid_rules, list) else []
        rules_container = legacy_rules if legacy_rules is not None else set()
        mock_reply = {"lang": "ru", "text": text_input, "cited": cited_input}
        res = sanitize_draft(mock_reply, rules_container)
        return res["text"], res["cited"]

    if not isinstance(draft_reply, dict):
        return draft_reply

    rules_set: set[str] = (
        set(valid_rules.keys()) if isinstance(valid_rules, dict) else set(valid_rules)
    )

    lang = draft_reply.get("lang", "ru")
    text = draft_reply.get("text", "") or ""
    cited = list(draft_reply.get("cited", []))

    # 1. Neutralize forbidden promises
    for pattern, replacement in FORBIDDEN_PROMISES:
        text = pattern.sub(replacement, text)

    # 2. Filter cited: keep only elements present in valid_rules
    clean_cited = [str(r).strip() for r in cited if str(r).strip() in rules_set]

    # 3. Paranoid scan for rule-like numbers in text
    found_numbers = RULE_NUMBER_PATTERN.findall(text)
    has_hallucination = any(num not in rules_set for num in found_numbers)

    if has_hallucination:
        text = SAFE_FALLBACK_TEXT
        clean_cited = []
    else:
        text = re.sub(r"\s{2,}", " ", text).strip()

    return {
        "lang": lang,
        "text": text,
        "cited": clean_cited,
    }
