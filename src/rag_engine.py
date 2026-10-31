import functools
import os
import re
from typing import Any

import orjson
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

SLANG_MAP = {
    "дм": ["5.3", "5.4", "1.1"],
    "dm": ["5.3", "5.4", "1.1"],
    "deathmatch": ["5.3", "5.4"],
    "дб": ["5.3", "5.5"],
    "db": ["5.3", "5.5"],
    "ск": ["5.4"],
    "sk": ["5.4"],
    "тк": ["5.3"],
    "tk": ["5.3"],
    "оск": ["2.1"],
    "оскорбление": ["2.1"],
    "оск род": ["2.1"],
    "оск родни": ["2.1"],
    "упом род": ["2.1"],
    "упом родни": ["2.1"],
    "упоминание родителей": ["2.1"],
    "неадекват": ["2.1"],
    "неадыкват": ["2.1"],
    "неадекватное поведение": ["2.1"],
    "мат": ["2.1"],
    "матерится": ["2.1"],
    "обзывает": ["2.1"],
    "общается с матом": ["2.1"],
    "оскр": ["2.1"],
    "osk": ["2.1"],
    "haromi": ["2.1"],
    "harom": ["2.1"],
    "боқтау": ["2.1"],
    "боқтық": ["2.1"],
    "балағат": ["2.1"],
    "расизм": ["2.4"],
    "национальность": ["2.4"],
    "розжиг": ["2.4"],
    "межнац": ["2.4"],
    "страны и национальности": ["2.4"],
    "транс": ["2.4"],
    "лгбт": ["2.4"],
    "нрп": ["5.3", "5.1"],
    "nonrp": ["5.3", "5.1"],
    "нонрп": ["5.3", "5.1"],
    "уход от рп": ["5.3"],
    "урп": ["5.3"],
    "чит": ["5.2"],
    "читы": ["5.2"],
    "софт": ["5.2"],
    "аим": ["5.2"],
    "вх": ["5.2"],
    "рванка": ["5.2"],
    "бот": ["5.2"],
    "кликер": ["5.2"],
    "скам": ["4.1", "4.2"],
    "обман": ["4.1", "4.2"],
    "развод": ["4.1"],
    "махинации": ["4.1"],
    "вирты": ["4.1", "4.4"],
    "донат": ["1.4"],
    "взлом": ["1.4", "1.7"],
    "реклама": ["2.3"],
    "пиар": ["2.3"],
    "оффтоп": ["3.1"],
    "флуд": ["3.1"],
    "зз": ["1.1", "1.2"],
    "gz": ["1.1", "1.2"],
    "зеленая зона": ["1.1", "1.2"],
    "зелёная зона": ["1.1", "1.2"],
}

CATEGORY_RULES_MAP = {
    "complaint.insult": ["2.1", "2.4"],
    "complaint.cheat": ["5.2"],
    "complaint.dm": ["5.3", "5.4", "1.1"],
    "complaint.scam": ["4.1", "4.2"],
    "complaint.rmt_ads": ["2.3", "4.4"],
    "complaint.admin": ["3.4"],
    "complaint.invalid": ["1.1", "1.2"],
    "report.help": ["3.1"],
    "report.account": ["1.4"],
    "report.offtopic": ["3.1"],
}


class RuleValidator:
    """
    УРОВЕНЬ 2: Валидация базы знаний (RAG Engine)
    - Загружает rules.json в память при старте сервера
    - Собирает все валидные ключи пунктов правил (например: '2.1', '3.4') в set() для O(1) проверки
    """

    def __init__(self, rules_path: str = "rules.json"):
        self.rules_path = rules_path
        self._valid_rules: set[str] = set()
        self._rules_dict: dict[str, dict[str, Any]] = {}
        self._points_list: list[dict[str, Any]] = []
        self._load_rules()

    def _load_rules(self) -> None:
        if not os.path.exists(self.rules_path):
            return
        try:
            with open(self.rules_path, "rb") as f:
                data = orjson.loads(f.read())
        except Exception:
            import json
            with open(self.rules_path, "r", encoding="utf-8") as f:
                data = json.load(f)

        for section in data.get("rules", []):
            section_title = section.get("category", "")
            section_id = section.get("id")
            for pt in section.get("points", []):
                ref = str(pt.get("ref", "")).strip()
                text = str(pt.get("text", "")).strip()
                if not ref or not text:
                    continue

                self._valid_rules.add(ref)
                item = {
                    "ref": ref,
                    "section_id": section_id,
                    "section": section_title,
                    "text": text,
                    "search_doc": f"{ref} {section_title} {text}".lower(),
                }
                if ref not in self._rules_dict:
                    self._rules_dict[ref] = item
                self._points_list.append(item)

    def get_valid_rules(self) -> set[str]:
        """Возвращает set всех проверенных ключей пунктов правил для O(1) проверки."""
        return self._valid_rules

    def is_valid(self, ref: str) -> bool:
        """Мгновенно валидирует пункт правил за O(1)."""
        return str(ref).strip() in self._valid_rules

    def get_rules_dict(self) -> dict[str, dict[str, Any]]:
        """Возвращает справочник пунктов правил."""
        return self._rules_dict

    def get_points_list(self) -> list[dict[str, Any]]:
        return self._points_list

    def __contains__(self, ref: str) -> bool:
        return str(ref).strip() in self._valid_rules

    def __len__(self) -> int:
        return len(self._valid_rules)


_GLOBAL_RAG_CACHE: dict[str, Any] = {}


def get_or_load_rag_index(rules_path: str = "rules.json") -> dict[str, Any]:
    """Загружает базу rules.json и строит TF-IDF индекс один раз в память (Singleton Cache)."""
    global _GLOBAL_RAG_CACHE
    if rules_path in _GLOBAL_RAG_CACHE:
        return _GLOBAL_RAG_CACHE[rules_path]

    validator = RuleValidator(rules_path)
    rules_dict = validator.get_rules_dict()
    points_list = validator.get_points_list()

    vectorizer = None
    tfidf_matrix = None
    if points_list:
        docs = [p["search_doc"] for p in points_list]
        vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=1)
        tfidf_matrix = vectorizer.fit_transform(docs)

    cached_entry = {
        "validator": validator,
        "rules_dict": rules_dict,
        "points_list": points_list,
        "vectorizer": vectorizer,
        "tfidf_matrix": tfidf_matrix,
    }
    _GLOBAL_RAG_CACHE[rules_path] = cached_entry
    return cached_entry


class RAGEngine:
    """
    Гибридный RAG-движок для правил Grand Mobile:
    - Индексация пунктов правил из rules.json
    - Точное сопоставление по номеру пункта (ref)
    - Лексический поиск с помощью TF-IDF
    - Понимание игрового сленга и аббревиатур (дм, дб, ск, оск род, софт и др.)
    """

    def __init__(self, rules_path: str = "rules.json"):
        self.rules_path = rules_path
        index_data = get_or_load_rag_index(rules_path)
        self.validator: RuleValidator = index_data["validator"]
        self.rules_dict: dict[str, dict[str, Any]] = index_data["rules_dict"]
        self.points_list: list[dict[str, Any]] = index_data["points_list"]
        self.vectorizer: TfidfVectorizer | None = index_data["vectorizer"]
        self.tfidf_matrix = index_data["tfidf_matrix"]

    def get_valid_rules_dict(self) -> dict[str, dict[str, Any]]:
        return self.rules_dict

    def get_valid_rules(self) -> set[str]:
        return self.validator.get_valid_rules()

    @functools.lru_cache(maxsize=2048)
    def _cached_search_refs(
        self,
        query_lower: str,
        category: str | None,
        extracted_refs_tuple: tuple[str, ...],
        top_k: int,
    ) -> tuple[str, ...]:
        results: dict[str, bool] = {}

        # 1. Compound game patterns
        if any(
            w in query_lower
            for w in [
                "веревк",
                "связал",
                "похищ",
                "мешок",
                "связать",
                "веревка",
                "веревки",
            ]
        ) and any(w in query_lower for w in ["зз", "gz", "зелен"]):
            if "1.2" in self.rules_dict:
                results["1.2"] = True

        elif any(w in query_lower for w in ["mass db", "db in gz", "dm in gz"]) or (
            any(
                w in query_lower
                for w in [
                    "дм",
                    "дб",
                    "dm",
                    "db",
                    "убил",
                    "стрельб",
                    "убийств",
                ]
            )
            and any(w in query_lower for w in ["зз", "gz", "зелен"])
        ):
            for r in ["1.1", "5.3"]:
                if r in self.rules_dict and r not in results:
                    results[r] = True

        # Racism / nationality / trans -> 2.4
        if any(
            w in query_lower
            for w in [
                "расизм",
                "национальн",
                "розжиг",
                "межнац",
                "страны и национальности",
                "транс",
                "лгбт",
            ]
        ):
            if "2.4" in self.rules_dict:
                results["2.4"] = True

        # SpawnKill (SK) -> 5.4
        if (
            re.search(r"\b(?:sk|ск)\b", query_lower)
            or "спавн" in query_lower
            or "у дома" in query_lower
        ):
            if "5.4" in self.rules_dict and "5.4" not in results:
                results["5.4"] = True

        # 2. Slang / abbreviation matching
        for slang, target_refs in SLANG_MAP.items():
            if re.search(r"\b" + re.escape(slang) + r"\b", query_lower):
                for r in target_refs:
                    if r in self.rules_dict and r not in results:
                        results[r] = True

        # 3. Direct match from extracted refs
        if extracted_refs_tuple:
            for ref in extracted_refs_tuple:
                ref_clean = str(ref).strip()
                if ref_clean in self.rules_dict and ref_clean not in results:
                    results[ref_clean] = True

        # 4. Category fallback mapping
        if category and category in CATEGORY_RULES_MAP:
            for r in CATEGORY_RULES_MAP[category]:
                if r in self.rules_dict and r not in results:
                    results[r] = True

        # 5. Fast sparse TF-IDF dot-product retrieval if needed
        if len(results) < top_k and self.vectorizer is not None and query_lower.strip():
            query_vec = self.vectorizer.transform([query_lower])
            sims = self.tfidf_matrix.dot(query_vec.T).toarray().ravel()
            top_indices = sims.argsort()[::-1]
            for idx in top_indices:
                if len(results) >= top_k:
                    break
                if sims[idx] > 0.12:
                    pt = self.points_list[idx]
                    ref = pt["ref"]
                    if ref not in results and ref in self.rules_dict:
                        results[ref] = True

        return tuple(results.keys())[:top_k]

    def retrieve(
        self,
        query: str,
        category: str | None = None,
        extracted_refs: list[str] | None = None,
        top_k: int = 4,
    ) -> list[dict[str, Any]]:
        """
        Ищет наиболее релевантные пункты правил с использованием LRU-кэша.
        Гарантирует возврат только реально существующих пунктов из rules.json.
        """
        query_lower = query.lower().replace("ё", "е")
        refs_tuple = tuple(extracted_refs) if extracted_refs else ()
        matched_refs = self._cached_search_refs(query_lower, category, refs_tuple, top_k)
        return [self.rules_dict[r] for r in matched_refs if r in self.rules_dict]
