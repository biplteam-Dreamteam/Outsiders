import re
from typing import Any

try:
    import core_engine
    HAS_CPP_CORE = True
except ImportError:
    HAS_CPP_CORE = False

CP1251_KZ_MAPPING = {
    "ќ": "қ",
    "Ќ": "Қ",
    "ґ": "ғ",
    "Ґ": "Ғ",
    "ѕ": "ң",
    "Ѕ": "Ң",
    "є": "ә",
    "Є": "Ә",
    "ј": "ө",
    "Ј": "Ө",
    "ў": "ұ",
    "Ў": "Ұ",
    "ї": "ү",
    "Ї": "Ү",
}
CP1251_KZ_TRANSLATE_TABLE = str.maketrans(CP1251_KZ_MAPPING)

KK_LETTERS = set("әғқңөұүһіӘҒҚҢӨҰҮҺІ")
KK_WORDS = {
    "сәлем",
    "салем",
    "рахмет",
    "болады",
    "қандай",
    "кандай",
    "неге",
    "қалай",
    "калай",
    "болды",
    "керек",
    "жасау",
    "өтініш",
    "отиниш",
    "мені",
    "мени",
    "барма",
    "жоқ",
    "жок",
    "маған",
    "маган",
    "қайда",
    "кайда",
    "айтыңызшы",
    "айтынызшы",
    "шығар",
    "шыгар",
    "берші",
    "берши",
    "қайырлы",
    "көмек",
    "комек",
    "болама",
    "ойнау",
    "акша",
    "ақша",
    "жумыс",
    "жұмыс",
    "үй",
    "үйім",
    "машина",
    "жаза",
    "шағым",
    "шагым",
    "ойыншы",
    "дəлел",
    "дәлел",
    "басталды",
    "кетті",
}

UZ_MARKERS = {"o'", "g'", "o`", "g`", "sh", "ch", "yo", "yu", "ya"}
UZ_WORDS = {
    "iltimos",
    "yordam",
    "qanday",
    "nima",
    "xush",
    "rahmat",
    "kerak",
    "bormi",
    "qilish",
    "qildim",
    "salom",
    "aka",
    "tashab",
    "bering",
    "yozing",
    "oldirdi",
    "mesabab",
    "qildi",
    "pul",
    "ish",
    "oyin",
    "moshin",
    "qayerda",
    "blok",
    "adminlar",
    "sabab",
    "haqida",
    "berish",
    "yordamchi",
    "qanaqa",
}

EN_WORDS = {
    "help",
    "please",
    "how",
    "what",
    "why",
    "stuck",
    "ban",
    "admin",
    "report",
    "game",
    "car",
    "money",
    "player",
    "bug",
    "issue",
    "unban",
    "hack",
    "hacker",
    "server",
    "login",
    "lost",
    "password",
    "spawn",
    "kill",
    "cheater",
    "aimbot",
}

NICKNAME_PATTERN = re.compile(r"\b[A-ZА-ЯЁ][a-zа-яё0-9]+_[A-ZА-ЯЁ][a-zа-яё0-9]+\b")
RULE_REF_PATTERN = re.compile(r"\b\d+\.\d+(?:\.\d+)?\b")
EVIDENCE_PATTERNS = [
    r"скрин",
    r"видео",
    r"фрапс",
    r"пруф",
    r"доказ",
    r"доки",
    r"запись",
    r"<url>",
    r"дәлел",
    r"далел",
    r"skrin",
    r"video",
    r"proof",
    r"dalil",
    r"dalillar",
    r"screen",
    r"screenshot",
    r"зафиксировал",
    r"заснял",
    r"снял",
]
EVIDENCE_REGEX = re.compile("|".join(EVIDENCE_PATTERNS), re.IGNORECASE)
SERVER_PATTERN = re.compile(
    r"(?:сервер[а-я]*|server)\s*[:#№]?\s*(\d+|[a-zA-Z]+)", re.IGNORECASE
)
WHITESPACE_NEWLINES_RE = re.compile(r"[\r\n\t]+")
WHITESPACE_MULTI_RE = re.compile(r"\s{2,}")
WORD_TOKEN_RE = re.compile(r"[a-zA-Zа-яА-ЯёЁ\'`]+")
GZ_PATTERN = re.compile(r"\b(?:gz|гз|зз)\b", re.IGNORECASE)


def normalize_cp1251_kz(text: str) -> str:
    """Заменяет искаженные символы кодировки cp1251 на правильные казахские буквы через C++ core или str.translate()."""
    if not text:
        return ""
    if HAS_CPP_CORE:
        return core_engine.fix_cp1251_kz(text)
    text_norm = text.translate(CP1251_KZ_TRANSLATE_TABLE)
    text_norm = WHITESPACE_NEWLINES_RE.sub(" ", text_norm)
    return WHITESPACE_MULTI_RE.sub(" ", text_norm).strip()


def detect_language(text: str, default_lang: str | None = None) -> str:
    """
    Быстрое мультиязычное определение языка: ru, kk, uz, en, und.
    Использует алфавитные маркеры, казахскую кириллицу, узбекскую латиницу и лексические словари.
    """
    if not text or len(text.strip()) == 0:
        return default_lang or "und"

    text_norm = normalize_cp1251_kz(text)
    text_lower = text_norm.lower()

    # 1. Kazakh Cyrillic letters check
    kz_char_count = sum(1 for ch in text_lower if ch in KK_LETTERS)
    if kz_char_count > 0:
        return "kk"

    # Tokenize words
    words = WORD_TOKEN_RE.findall(text_lower)
    if not words:
        return default_lang or "und"

    word_set = set(words)

    # 2. Kazakh vocabulary markers
    if word_set & KK_WORDS:
        return "kk"

    # 3. Uzbek latin markers
    uz_score = sum(1 for w in words if w in UZ_WORDS)
    if uz_score > 0:
        return "uz"
    # Check uzbek digrams in latin text
    latin_letters = sum(1 for ch in text_lower if "a" <= ch <= "z")
    cyr_letters = sum(1 for ch in text_lower if "а" <= ch <= "я" or ch == "ё")

    if latin_letters > cyr_letters:
        # Check uzbek specific digraphs like o', g', sh, ch
        for marker in ["o'", "g'", "o`", "g`"]:
            if marker in text_lower:
                return "uz"
        # English words check
        en_score = sum(1 for w in words if w in EN_WORDS)
        if en_score > 0 or (
            "the" in word_set or "and" in word_set or "you" in word_set
        ):
            return "en"
        # If Latin server_lang was uz/en, fallback
        if default_lang in ("uz", "en", "kk", "ru"):
            return default_lang
        # If predominantly Latin without English markers, could be uz or lat
        return "uz" if default_lang == "uz" else "en"

    # 4. Cyrillic text -> Russian
    if cyr_letters > 0:
        return "ru"

    return default_lang or "und"


def extract_facts(
    ticket: dict[str, Any],
    text: str | None = None,
    rule_refs_raw: str | None = None,
    images_count: int | None = None,
) -> dict[str, Any]:
    r"""
    Экстрактор фактов:
    - nickname (паттерны вида Name_Surname или токен <nick>)
    - rule_refs (регулярка \b\d+\.\d+\b из rule_refs_raw и текста, плюс сленг)
    - has_evidence (images_count > 0 или маркеры доказательств)
    - server (номер или название сервера)
    """
    if text is None:
        # Collect text from player messages
        raw_msgs = ticket.get("messages") or []
        player_msgs = [
            m.get("text", "")
            for m in (raw_msgs if isinstance(raw_msgs, list) else [])
            if isinstance(m, dict) and m.get("role") == "player"
        ]
        text = " ".join(player_msgs)

    text_norm = normalize_cp1251_kz(text)
    raw_refs = rule_refs_raw or ticket.get("rule_refs_raw", "") or ""
    raw_refs_norm = normalize_cp1251_kz(str(raw_refs))
    try:
        raw_val = images_count if images_count is not None else (ticket.get("images_count") or ticket.get("attachments") or 0)
        img_cnt = max(0, int(raw_val))
    except Exception:
        img_cnt = 0

    if HAS_CPP_CORE:
        rep_nick = str(ticket.get("reported_nick") or "")
        srv_str = str(ticket.get("region") or ticket.get("server_lang") or "")
        cpp_res = core_engine.extract_facts_cpp(
            text, str(raw_refs), int(img_cnt), rep_nick, srv_str
        )
        return {
            "nickname": cpp_res.get("nickname"),
            "rule_refs": cpp_res.get("rule_refs", []),
            "has_evidence": bool(cpp_res.get("has_evidence", False)),
            "server": cpp_res.get("server"),
        }

    # 1. Nickname
    nick = ticket.get("reported_nick")
    if not nick or nick == "None":
        # Search in text
        match_nick = NICKNAME_PATTERN.search(text_norm)
        if match_nick:
            nick = match_nick.group(0)
        elif "<nick>" in text_norm:
            nick = "<nick>"
        else:
            nick = None

    # 2. Rule references
    refs_found = set()
    # From rule_refs_raw
    for match in RULE_REF_PATTERN.finditer(raw_refs_norm):
        refs_found.add(match.group(0))
    # From text
    for match in RULE_REF_PATTERN.finditer(text_norm):
        refs_found.add(match.group(0))

    # Check GZ / ЗЗ
    if GZ_PATTERN.search(raw_refs_norm + " " + text_norm):
        refs_found.add("GZ")

    rule_refs = sorted(refs_found)

    # 3. Evidence (images_count > 0, attachments > 0, or keywords)
    has_evidence = False
    if img_cnt > 0 or EVIDENCE_REGEX.search(text_norm):
        has_evidence = True

    # 4. Server
    server = None
    server_match = SERVER_PATTERN.search(text_norm)
    if server_match:
        server = server_match.group(1)
    elif ticket.get("region"):
        server = str(ticket.get("region"))
    elif ticket.get("server_lang"):
        server = str(ticket.get("server_lang"))

    return {
        "nickname": nick,
        "rule_refs": rule_refs,
        "has_evidence": bool(has_evidence),
        "server": server,
    }
