import functools
import json
import logging
import os
import re
from typing import Any

try:
    import core_engine
    HAS_CPP_CORE = True
except ImportError:
    HAS_CPP_CORE = False

import orjson
from sklearn.feature_extraction.text import TfidfVectorizer

from src.rule_manager import get_active_rules_path, parse_rules_content

logger = logging.getLogger("via-rag-engine")


class RuleValidator:
    """
    УРОВЕНЬ 2: Валидация базы знаний (Universal Knowledge Base Validator)
    - Загружает активные правила из data/active_rules.json или переданного источника
    - Собирает все валидные ключи пунктов правил (например: '1.1', '2.2') в set() для O(1) проверки
    - Поддерживает динамическую перезагрузку на лету (Hot-Reload)
    """

    def __init__(self, rules_path: str | None = None):
        self.rules_path = rules_path or get_active_rules_path()
        self._valid_rules: set[str] = set()
        self._rules_dict: dict[str, dict[str, Any]] = {}
        self._points_list: list[dict[str, Any]] = []
        self._load_rules()

    def _load_rules(self) -> None:
        if not os.path.exists(self.rules_path):
            # Fallback to active rules path
            self.rules_path = get_active_rules_path()
            if not os.path.exists(self.rules_path):
                return
        try:
            with open(self.rules_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            try:
                with open(self.rules_path, "rb") as f:
                    data = orjson.loads(f.read())
            except Exception as e:
                logger.error(f"Failed to read rules file {self.rules_path}: {e}")
                return

        self.load_from_data(data)

    def load_from_data(self, data: dict[str, Any] | list | str) -> None:
        """Парсит и загружает правила из произвольного объекта или текста."""
        parsed = parse_rules_content(data)
        self._valid_rules.clear()
        self._rules_dict.clear()
        self._points_list.clear()

        sec_counter = 1
        for section in parsed.get("rules", []):
            section_title = section.get("category") or section.get("title") or f"Раздел {sec_counter}"
            section_id = section.get("id", sec_counter)
            sec_counter += 1

            for pt in section.get("points", []):
                ref = str(pt.get("ref", "")).strip()
                text = str(pt.get("text", "")).strip()
                title = str(pt.get("title", "")).strip()
                cat = str(pt.get("category", "")).strip()
                kw = pt.get("keywords", [])
                kw_str = " ".join(kw) if isinstance(kw, list) else str(kw)

                if not ref or not text:
                    continue

                self._valid_rules.add(ref)
                item = {
                    "ref": ref,
                    "section_id": section_id,
                    "section": section_title,
                    "title": title,
                    "category": cat,
                    "keywords": kw if isinstance(kw, list) else [str(kw)],
                    "text": text,
                    "search_doc": f"{ref} {section_title} {title} {kw_str} {text}".lower(),
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


def get_or_load_rag_index(rules_path: str | None = None) -> dict[str, Any]:
    """Загружает базу знаний и строит TF-IDF индекс один раз в память (Singleton Cache)."""
    global _GLOBAL_RAG_CACHE
    path = rules_path or get_active_rules_path()
    if path in _GLOBAL_RAG_CACHE:
        return _GLOBAL_RAG_CACHE[path]

    validator = RuleValidator(path)
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
    _GLOBAL_RAG_CACHE[path] = cached_entry
    return cached_entry


class RAGEngine:
    """
    Универсальный гибридный RAG-движок для корпоративных регламентов и баз знаний:
    - Точное сопоставление по номеру пункта (ref)
    - Семантический поиск по ключевым словам и заголовкам
    - Лексический поиск с помощью TF-IDF
    - Динамическая перезагрузка при обновлении правил без перезапуска сервиса
    """

    def __init__(self, rules_path: str | None = None):
        self.rules_path = rules_path or get_active_rules_path()
        self._init_from_path(self.rules_path)

    def _init_from_path(self, path: str):
        self.rules_path = path
        index_data = get_or_load_rag_index(path)
        self.validator: RuleValidator = index_data["validator"]
        self.rules_dict: dict[str, dict[str, Any]] = index_data["rules_dict"]
        self.points_list: list[dict[str, Any]] = index_data["points_list"]
        self.vectorizer: TfidfVectorizer | None = index_data["vectorizer"]
        self.tfidf_matrix = index_data["tfidf_matrix"]

    def reload_rules(self, rules_source: str | dict | list | None = None) -> None:
        """Перезагружает базу правил и перестраивает TF-IDF векторную матрицу."""
        global _GLOBAL_RAG_CACHE
        if isinstance(rules_source, str) and os.path.exists(rules_source):
            self.rules_path = rules_source
            _GLOBAL_RAG_CACHE.pop(self.rules_path, None)
            self._init_from_path(self.rules_path)
        else:
            # Прямая загрузка структуры в память
            source_data = rules_source or get_active_rules_path()
            if isinstance(source_data, str) and os.path.exists(source_data):
                self._init_from_path(source_data)
            else:
                self.validator.load_from_data(source_data)
                self.rules_dict = self.validator.get_rules_dict()
                self.points_list = self.validator.get_points_list()
                if self.points_list:
                    docs = [p["search_doc"] for p in self.points_list]
                    self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=1)
                    self.tfidf_matrix = self.vectorizer.fit_transform(docs)
                else:
                    self.vectorizer = None
                    self.tfidf_matrix = None

        # Очищаем LRU кэш поиска
        self._cached_search_refs.cache_clear()
        logger.info(f"RAGEngine re-indexed: {len(self.rules_dict)} rules active")

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

        # 1. Direct match from extracted refs
        if extracted_refs_tuple:
            for ref in extracted_refs_tuple:
                ref_clean = str(ref).strip()
                if ref_clean in self.rules_dict and ref_clean not in results:
                    results[ref_clean] = True

        # 2. Dynamic Keyword & Title Matching over active rules
        query_words = set(re.findall(r"\w+", query_lower))
        if query_words:
            for pt in self.points_list:
                ref = pt["ref"]
                if ref in results:
                    continue
                # Проверка ключевых слов правила
                keywords = pt.get("keywords", [])
                for kw in keywords:
                    kw_lower = str(kw).lower()
                    if kw_lower and kw_lower in query_lower:
                        results[ref] = True
                        break
                if len(results) >= top_k:
                    break

        # 3. Category match
        if category and len(results) < top_k:
            for pt in self.points_list:
                ref = pt["ref"]
                if ref not in results and pt.get("category") == category:
                    results[ref] = True
                    if len(results) >= top_k:
                        break

        # 4. Sparse TF-IDF Cosine Search
        if len(results) < top_k and self.vectorizer is not None and query_lower.strip():
            try:
                query_vec = self.vectorizer.transform([query_lower])
                sims = self.tfidf_matrix.dot(query_vec.T).toarray().ravel()
                top_indices = sims.argsort()[::-1]
                for idx in top_indices:
                    if len(results) >= top_k:
                        break
                    if sims[idx] > 0.08:
                        ref = self.points_list[idx]["ref"]
                        if ref not in results and ref in self.rules_dict:
                            results[ref] = True
            except Exception:
                pass

        # 5. C++ Fuzzy Levenshtein match (if available)
        if HAS_CPP_CORE and len(results) < top_k and query_lower.strip():
            try:
                rule_texts = [p["search_doc"] for p in self.points_list]
                rule_refs = [p["ref"] for p in self.points_list]
                cpp_matched = core_engine.fuzzy_match_rule(query_lower, rule_texts, rule_refs, 0.65)
                for ref in cpp_matched:
                    if len(results) >= top_k:
                        break
                    if ref not in results and ref in self.rules_dict:
                        results[ref] = True
            except Exception:
                pass

        return tuple(results.keys())[:top_k]

    def retrieve(
        self,
        query: str,
        category: str | None = None,
        extracted_refs: list[str] | None = None,
        top_k: int = 4,
    ) -> list[dict[str, Any]]:
        """
        Ищет наиболее релевантные пункты правил в активной базе знаний.
        Гарантирует возврат только реально существующих пунктов.
        """
        query_lower = query.lower().replace("ё", "е")
        refs_tuple = tuple(extracted_refs) if extracted_refs else ()
        matched_refs = self._cached_search_refs(query_lower, category, refs_tuple, top_k)
        return [self.rules_dict[r] for r in matched_refs if r in self.rules_dict]
