import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger("via-rule-manager")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
ACTIVE_RULES_PATH = os.path.join(DATA_DIR, "active_rules.json")
DEFAULT_RULES_PATH = os.path.join(DATA_DIR, "default_enterprise_rules.json")


def get_active_rules_path() -> str:
    """Возвращает путь к активной базе знаний, при необходимости инициализируя ее."""
    if os.path.exists(ACTIVE_RULES_PATH):
        return ACTIVE_RULES_PATH
    if os.path.exists(DEFAULT_RULES_PATH):
        return DEFAULT_RULES_PATH
    # Legacy fallback
    legacy = os.path.join(BASE_DIR, "rules.json")
    if os.path.exists(legacy):
        return legacy
    return ACTIVE_RULES_PATH


def parse_rules_content(content: str | dict | list) -> dict[str, Any]:
    """
    Универсальный парсер правил и регламентов:
    - Поддерживает стандартный JSON со структурой разделов и пунктов
    - Поддерживает плоский JSON список: [{"ref": "1.1", "text": "...", ...}]
    - Поддерживает словарь ключ-значение: {"1.1": "Текст правила"}
    - Поддерживает текстовые файлы Markdown / TXT с разбивкой по заголовкам или статьям
    """
    # 1. Если на вход уже передан словарь
    if isinstance(content, dict):
        if "rules" in content and isinstance(content["rules"], list):
            return normalize_rules_schema(content)
        # Если это плоский dict вида {"1.1": "текст"} или {"1.1": {"text": ...}}
        return dict_to_rules_schema(content)

    # 2. Если на вход передан список
    if isinstance(content, list):
        return list_to_rules_schema(content)

    # 3. Если передан текст
    text_content = str(content).strip()

    # Попытка распарсить как JSON
    if (text_content.startswith("{") and text_content.endswith("}")) or (
        text_content.startswith("[") and text_content.endswith("]")
    ):
        try:
            parsed_json = json.loads(text_content)
            return parse_rules_content(parsed_json)
        except Exception:
            pass

    # Парсинг Markdown / Plain Text
    return parse_markdown_rules(text_content)


def normalize_rules_schema(data: dict[str, Any]) -> dict[str, Any]:
    """Валидирует и нормализует стандартную схему правил."""
    sections = []
    sec_id = 1
    for sec in data.get("rules", []):
        sec_title = sec.get("category") or sec.get("title") or f"Раздел {sec_id}"
        points = []
        pt_counter = 1
        for pt in sec.get("points", []):
            ref = str(pt.get("ref") or f"{sec_id}.{pt_counter}").strip()
            title = pt.get("title") or f"Пункт {ref}"
            text = str(pt.get("text") or "").strip()
            cat = pt.get("category") or infer_category_slug(sec_title, title)
            kw = pt.get("keywords") or []
            if not text:
                continue
            points.append({
                "ref": ref,
                "title": title,
                "category": cat,
                "keywords": kw if isinstance(kw, list) else [str(kw)],
                "text": text,
            })
            pt_counter += 1

        if points:
            sections.append({
                "id": sec_id,
                "category": sec_title,
                "points": points,
            })
            sec_id += 1

    return {
        "name": data.get("name", "Пользовательская база знаний"),
        "version": data.get("version", "1.0.0"),
        "description": data.get("description", "Регламент компании"),
        "rules": sections,
    }


def dict_to_rules_schema(data: dict[str, Any]) -> dict[str, Any]:
    points = []
    for k, v in data.items():
        ref = str(k).strip()
        if isinstance(v, dict):
            text = str(v.get("text") or v.get("description") or "").strip()
            title = str(v.get("title") or f"Пункт {ref}").strip()
            cat = v.get("category") or f"rule.{ref}"
            kw = v.get("keywords") or []
        else:
            text = str(v).strip()
            title = f"Пункт {ref}"
            cat = f"rule.{ref}"
            kw = []
        if text:
            points.append({
                "ref": ref,
                "title": title,
                "category": cat,
                "keywords": kw,
                "text": text,
            })

    return {
        "name": "Импортированная база знаний",
        "version": "1.0.0",
        "rules": [
            {
                "id": 1,
                "category": "Общий регламент",
                "points": points,
            }
        ],
    }


def list_to_rules_schema(data: list[Any]) -> dict[str, Any]:
    points = []
    counter = 1
    for item in data:
        if isinstance(item, dict):
            ref = str(item.get("ref") or f"1.{counter}").strip()
            title = str(item.get("title") or f"Статья {ref}").strip()
            text = str(item.get("text") or item.get("body") or "").strip()
            cat = str(item.get("category") or "general.rule").strip()
            kw = item.get("keywords") or []
        else:
            ref = f"1.{counter}"
            title = f"Статья {ref}"
            text = str(item).strip()
            cat = "general.rule"
            kw = []
        if text:
            points.append({
                "ref": ref,
                "title": title,
                "category": cat,
                "keywords": kw if isinstance(kw, list) else [str(kw)],
                "text": text,
            })
            counter += 1

    return {
        "name": "Импортированный список правил",
        "version": "1.0.0",
        "rules": [
            {
                "id": 1,
                "category": "Регламент обслуживания",
                "points": points,
            }
        ],
    }


def parse_markdown_rules(text: str) -> dict[str, Any]:
    """Разбирает текстовые или Markdown регламенты по заголовкам и пунктам."""
    lines = text.split("\n")
    sections = []
    current_sec_title = "Общие положения"
    current_points = []
    sec_id = 1
    pt_id = 1

    for line in lines:
        line_clean = line.strip()
        if not line_clean:
            continue

        # Заголовок раздела (# Раздел 1 или ## Раздел)
        if line_clean.startswith("#"):
            title = re.sub(r"^#+\s*", "", line_clean)
            if current_points:
                sections.append({
                    "id": sec_id,
                    "category": current_sec_title,
                    "points": current_points,
                })
                sec_id += 1
                current_points = []
                pt_id = 1
            current_sec_title = title
            continue

        # Пункт правила (например, 1.1 Текст или Пункт 2: Текст или - Текст)
        match_ref = re.match(r"^(\d+\.\d+|\d+\)|\d+\.)\s*(.*)", line_clean)
        if match_ref:
            raw_ref = match_ref.group(1).rstrip(").")
            body = match_ref.group(2).strip()
            ref = f"{sec_id}.{pt_id}" if "." not in raw_ref else raw_ref
            current_points.append({
                "ref": ref,
                "title": f"Пункт {ref}",
                "category": infer_category_slug(current_sec_title, f"Пункт {ref}"),
                "keywords": [],
                "text": body,
            })
            pt_id += 1
        elif line_clean.startswith("- ") or line_clean.startswith("* "):
            body = line_clean[2:].strip()
            ref = f"{sec_id}.{pt_id}"
            current_points.append({
                "ref": ref,
                "title": f"Положение {ref}",
                "category": infer_category_slug(current_sec_title, f"Положение {ref}"),
                "keywords": [],
                "text": body,
            })
            pt_id += 1
        else:
            # Обычный текст - если уже есть текущий пункт, дописываем к нему
            if current_points:
                current_points[-1]["text"] += f" {line_clean}"
            else:
                ref = f"{sec_id}.{pt_id}"
                current_points.append({
                    "ref": ref,
                    "title": f"Статья {ref}",
                    "category": infer_category_slug(current_sec_title, f"Статья {ref}"),
                    "keywords": [],
                    "text": line_clean,
                })
                pt_id += 1

    if current_points:
        sections.append({
            "id": sec_id,
            "category": current_sec_title,
            "points": current_points,
        })

    return {
        "name": "Импортированный Markdown регламент",
        "version": "1.0.0",
        "rules": sections,
    }


def infer_category_slug(sec_title: str, pt_title: str) -> str:
    """Генерирует аккуратный слаг категории из названия раздела."""
    combined = f"{sec_title} {pt_title}".lower()
    if any(w in combined for w in ["плат", "оплат", "деньг", "биллинг", "чек", "транзакц", "возврат"]):
        return "billing.payment" if "возврат" not in combined else "billing.refund"
    if any(w in combined for w in ["аккаунт", "парол", "взлом", "безопасн", "вход", "доступ", "авториз"]):
        return "account.security" if "восстанов" not in combined else "account.recovery"
    if any(w in combined for w in ["ошибк", "баг", "сбой", "не работает", "краш", "вылет"]):
        return "tech.bug"
    if any(w in combined for w in ["оскорб", "мат", "хам", "модерац", "правила общения"]):
        return "moderation.abuse"
    if any(w in combined for w in ["спам", "флуд", "реклам"]):
        return "moderation.spam"
    if any(w in combined for w in ["доставк", "курьер", "заказ", "посылк"]):
        return "order.delivery"
    if any(w in combined for w in ["товар", "брак", "обмен"]):
        return "product.quality"
    # Транслитерация первых двух слов раздела
    words = re.findall(r"[a-zA-Zа-яА-Я0-9]+", sec_title.lower())[:2]
    clean_tag = ".".join(words) if words else "custom.policy"
    return clean_tag


def save_active_rules(parsed_rules: dict[str, Any]) -> str:
    """Сохраняет структурированные правила в data/active_rules.json."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(ACTIVE_RULES_PATH, "w", encoding="utf-8") as f:
        json.dump(parsed_rules, f, ensure_ascii=False, indent=2)
    logger.info(f"Active rules successfully saved to {ACTIVE_RULES_PATH}")
    return ACTIVE_RULES_PATH


def extract_categories_from_rules(parsed_rules: dict[str, Any]) -> list[str]:
    """Извлекает уникальный список всех категорий из базы правил."""
    categories = set()
    for sec in parsed_rules.get("rules", []):
        for pt in sec.get("points", []):
            cat = pt.get("category")
            if cat:
                categories.add(str(cat).strip())
    return sorted(list(categories))
