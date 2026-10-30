import re
from typing import Any

HUMAN_REQUIRED_CATEGORIES = {"report.account", "report.payment", "complaint.admin"}

# Multilingual keywords for high-risk / human required topics
PAYMENT_KEYWORDS = {
    # ru
    "донат",
    "donate",
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
    "қолжетімділік жоғалды",
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


def sanitize_draft(
    draft_text: str, cited: list[str], valid_rules_dict: dict[str, Any]
) -> tuple[str, list[str]]:
    """
    Пост-фильтр черновика ответа:
    1. Исключает ложные обещания разбана / возврата средств.
    2. Валидирует все пункты правил: если пункта нет в rules.json, удаляет из cited и текста.
    """
    if not draft_text:
        return "", []

    sanitized_text = draft_text

    # 1. Neutralize forbidden promises
    for pattern, replacement in FORBIDDEN_PROMISES:
        sanitized_text = pattern.sub(replacement, sanitized_text)

    # 2. Filter cited rule references
    clean_cited: list[str] = []
    for ref in cited:
        ref_clean = str(ref).strip()
        if ref_clean in valid_rules_dict:
            clean_cited.append(ref_clean)

    # 3. Search and clean any cited rule numbers in text that are not in valid_rules_dict
    rule_number_pattern = re.compile(r"\b(\d+\.\d+(?:\.\d+)?)\b")

    def ref_sub_check(match):
        num = match.group(1)
        if num in valid_rules_dict:
            return num
        # If hallucinated rule number, replace with general reference
        return "правил проекта"

    sanitized_text = rule_number_pattern.sub(ref_sub_check, sanitized_text)

    # Also clean duplicated spaces
    sanitized_text = re.sub(r"\s{2,}", " ", sanitized_text).strip()

    return sanitized_text, clean_cited
