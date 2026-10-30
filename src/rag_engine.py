import json
import os
import re
from typing import Dict, Any, List, Optional, Tuple
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from rapidfuzz import fuzz

SLANG_MAP = {
    'дм': ['5.3', '5.4', '1.1'],
    'dm': ['5.3', '5.4', '1.1'],
    'deathmatch': ['5.3', '5.4'],
    'дб': ['5.3', '5.5'],
    'db': ['5.3', '5.5'],
    'ск': ['5.4'],
    'sk': ['5.4'],
    'тк': ['5.3'],
    'tk': ['5.3'],
    'оск': ['2.1'],
    'оскорбление': ['2.1'],
    'оск род': ['2.1'],
    'упом род': ['2.1'],
    'мат': ['2.1'],
    'нрп': ['5.3', '5.1'],
    'nonrp': ['5.3', '5.1'],
    'нонрп': ['5.3', '5.1'],
    'уход от рп': ['5.3'],
    'чит': ['5.2'],
    'читы': ['5.2'],
    'софт': ['5.2'],
    'аим': ['5.2'],
    'вх': ['5.2'],
    'рванка': ['5.2'],
    'бот': ['5.2'],
    'кликер': ['5.2'],
    'скам': ['4.1', '4.2'],
    'обман': ['4.1', '4.2'],
    'развод': ['4.1'],
    'махинации': ['4.1'],
    'вирты': ['4.1', '4.4'],
    'донат': ['1.4'],
    'взлом': ['1.4', '1.7'],
    'реклама': ['2.3'],
    'пиар': ['2.3'],
    'оффтоп': ['3.1'],
    'флуд': ['3.1'],
    'зз': ['1.1', '1.2'],
    'gz': ['1.1', '1.2'],
    'зеленая зона': ['1.1', '1.2'],
    'зелёная зона': ['1.1', '1.2'],
}

CATEGORY_RULES_MAP = {
    "complaint.insult": ["2.1", "2.4", "2.6"],
    "complaint.cheat": ["5.2"],
    "complaint.dm": ["5.3", "5.4"],
    "complaint.scam": ["4.1", "4.2"],
    "complaint.rmt_ads": ["2.3", "4.4"],
    "complaint.admin": ["3.4"],
    "complaint.invalid": ["1.1", "1.2"],
    "report.help": ["3.1"],
    "report.account": ["1.4"],
    "report.offtopic": ["3.1"]
}


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
        self.rules_dict: Dict[str, Dict[str, Any]] = {}
        self.points_list: List[Dict[str, Any]] = []
        self.vectorizer: Optional[TfidfVectorizer] = None
        self.tfidf_matrix = None
        self._load_rules()

    def _load_rules(self):
        if not os.path.exists(self.rules_path):
            return

        with open(self.rules_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for rule_section in data.get("rules", []):
            section_title = rule_section.get("category", "")
            section_id = rule_section.get("id")
            for pt in rule_section.get("points", []):
                ref = str(pt.get("ref", "")).strip()
                text = pt.get("text", "").strip()
                if not ref or not text:
                    continue

                item = {
                    "ref": ref,
                    "section_id": section_id,
                    "section": section_title,
                    "text": text,
                    "search_doc": f"{ref} {section_title} {text}".lower()
                }
                # Keep first or best definition for ref in rules_dict
                if ref not in self.rules_dict:
                    self.rules_dict[ref] = item
                self.points_list.append(item)

        # Build TF-IDF search index
        if self.points_list:
            docs = [p["search_doc"] for p in self.points_list]
            self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=1)
            self.tfidf_matrix = self.vectorizer.fit_transform(docs)

    def get_valid_rules_dict(self) -> Dict[str, Dict[str, Any]]:
        return self.rules_dict

    def retrieve(
        self,
        query: str,
        category: Optional[str] = None,
        extracted_refs: Optional[List[str]] = None,
        top_k: int = 2
    ) -> List[Dict[str, Any]]:
        """
        Ищет наиболее релевантные пункты правил.
        Гарантирует возврат только реально существующих пунктов из rules.json.
        """
        results: Dict[str, Dict[str, Any]] = {}
        query_lower = query.lower()

        # 1. Direct match from extracted refs
        if extracted_refs:
            for ref in extracted_refs:
                ref_clean = str(ref).strip()
                if ref_clean in self.rules_dict and ref_clean not in results:
                    results[ref_clean] = self.rules_dict[ref_clean]

        # 2. Slang / abbreviation matching
        for slang, target_refs in SLANG_MAP.items():
            # Check whole word match or high fuzzy similarity
            if re.search(r'\b' + re.escape(slang) + r'\b', query_lower):
                for r in target_refs:
                    if r in self.rules_dict and r not in results:
                        results[r] = self.rules_dict[r]

        # 3. Category fallback mapping
        if category and category in CATEGORY_RULES_MAP:
            for r in CATEGORY_RULES_MAP[category]:
                if r in self.rules_dict and r not in results:
                    results[r] = self.rules_dict[r]

        # 4. TF-IDF retrieval if needed
        if len(results) < top_k and self.vectorizer is not None and query_lower.strip():
            query_vec = self.vectorizer.transform([query_lower])
            sims = cosine_similarity(query_vec, self.tfidf_matrix)[0]
            top_indices = sims.argsort()[::-1]
            for idx in top_indices:
                if len(results) >= top_k:
                    break
                if sims[idx] > 0.12:
                    pt = self.points_list[idx]
                    ref = pt["ref"]
                    if ref not in results and ref in self.rules_dict:
                        results[ref] = self.rules_dict[ref]

        return list(results.values())[:top_k]
