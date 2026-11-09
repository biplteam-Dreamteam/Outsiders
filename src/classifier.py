import json
import logging
import os
import re
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.preprocessor import normalize_cp1251_kz
from src.rule_manager import get_active_rules_path, parse_rules_content

logger = logging.getLogger("via-classifier")

MODEL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models"
)
CAT_MODEL_PATH = os.path.join(MODEL_DIR, "category_model.cbm")
PRIO_MODEL_PATH = os.path.join(MODEL_DIR, "priority_model.cbm")


class TicketClassifier:
    """
    Автономный динамический семантический классификатор (Universal Domain-Agnostic Classifier):
    - Не требует предварительно обученных игровых весов (.cbm)
    - Автоматически строит семантический индекс по категориям активной базы знаний (RAG)
    - Вычисляет категорию и уверенность (confidence) через TF-IDF n-gram косинусное сходство
    - Мгновенно адаптируется к любой загруженной базе знаний (E-commerce, SaaS, Финтех, Гейминг)
    - Автоматически определяет приоритет тикета (p0 - p3) на основе рисков безопасности и финансов
    """

    def __init__(
        self,
        cbm_path: str | None = None,
        prio_path: str | None = None,
        meta_path: str | None = None,
        thread_count: int | None = None,
        rules_path: str | None = None,
    ):
        self.rules_path = rules_path or get_active_rules_path()
        self.thread_count = thread_count
        self.categories: list[str] = []
        self.category_docs: dict[str, str] = {}
        self.rule_ref_to_cat: dict[str, str] = {}
        self.vectorizer: TfidfVectorizer | None = None
        self.category_matrix = None

        # Optional legacy CatBoost fallback if files exist
        self.catboost_model = None
        self.prio_model = None
        self._load_legacy_weights(cbm_path, prio_path)

        # Build dynamic semantic index from active rules
        self.reindex_from_rules(self.rules_path)

    def _load_legacy_weights(self, cbm_path: str | None, prio_path: str | None) -> None:
        cbm_file = cbm_path or CAT_MODEL_PATH
        prio_file = prio_path or PRIO_MODEL_PATH
        if os.path.exists(cbm_file):
            try:
                from catboost import CatBoostClassifier

                self.catboost_model = CatBoostClassifier()
                self.catboost_model.load_model(cbm_file)
            except Exception:
                self.catboost_model = None
        if os.path.exists(prio_file):
            try:
                from catboost import CatBoostClassifier

                self.prio_model = CatBoostClassifier()
                self.prio_model.load_model(prio_file)
            except Exception:
                self.prio_model = None

    def set_thread_count(self, threads: int) -> None:
        self.thread_count = max(1, int(threads))
        try:
            os.environ["OMP_NUM_THREADS"] = str(self.thread_count)
            os.environ["MKL_NUM_THREADS"] = str(self.thread_count)
        except Exception:
            pass

    def reindex_from_rules(self, rules_source: str | dict | list | None = None) -> None:
        """Динамически перестраивает классификатор на основе активных правил."""
        source = rules_source or self.rules_path
        data: dict[str, Any] = {}
        if isinstance(source, str) and os.path.exists(source):
            try:
                with open(source, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        elif isinstance(source, (dict, list)):
            data = parse_rules_content(source)

        if not data:
            # Fallback to default enterprise categories
            self.categories = [
                "support.faq",
                "support.sla",
                "account.security",
                "account.recovery",
                "billing.payment",
                "billing.refund",
                "tech.bug",
                "tech.outage",
                "moderation.abuse",
                "moderation.spam",
            ]
            return

        parsed = parse_rules_content(data)
        category_texts: dict[str, list[str]] = {}
        self.rule_ref_to_cat.clear()

        for sec in parsed.get("rules", []):
            sec_title = sec.get("category", "")
            for pt in sec.get("points", []):
                ref = str(pt.get("ref", "")).strip()
                title = str(pt.get("title", "")).strip()
                cat = str(pt.get("category") or "general.support").strip()
                text = str(pt.get("text", "")).strip()
                kw = pt.get("keywords", [])
                kw_str = " ".join(kw) if isinstance(kw, list) else str(kw)

                if ref and cat:
                    self.rule_ref_to_cat[ref] = cat

                if cat not in category_texts:
                    category_texts[cat] = []

                # Формируем семантический профиль категории
                category_texts[cat].append(f"{sec_title} {title} {kw_str} {text}")

        self.categories = sorted(list(category_texts.keys()))
        self.category_docs = {
            cat: " ".join(texts).lower() for cat, texts in category_texts.items()
        }

        if self.categories:
            docs = [self.category_docs[cat] for cat in self.categories]
            self.vectorizer = TfidfVectorizer(
                ngram_range=(1, 2),
                min_df=1,
                sublinear_tf=True,
            )
            self.category_matrix = self.vectorizer.fit_transform(docs)
            logger.info(
                f"Dynamic classifier reindexed: {len(self.categories)} categories active"
            )

    def is_trained(self) -> bool:
        """Система полностью функциональна и готова к автономной классификации."""
        return len(self.categories) > 0 and self.vectorizer is not None

    def predict_classes(
        self, text: str, kind: str = "complaint", images_count: int = 0
    ) -> dict[str, Any]:
        """
        Автономный высокоскоростной инференс:
        Определяет категорию по максимальной семантической близости к регламентам.
        """
        text_norm = normalize_cp1251_kz(str(text or ""))
        text_lower = text_norm.lower().replace("ё", "е")
        img_cnt = float(images_count or 0)

        category = None
        confidence = 0.75

        # 1. Прямой поиск ссылки на статью правил в тексте (например: "по пункту 2.1")
        clean_refs = re.findall(r"\b\d+\.\d+\b", text_norm)
        for r in clean_refs:
            if r in self.rule_ref_to_cat:
                category = self.rule_ref_to_cat[r]
                confidence = 0.95
                break

        # 2. Быстрый семантический поиск по профилям категорий через TF-IDF косинусное сходство
        if category is None and self.vectorizer is not None and self.category_matrix is not None:
            try:
                ticket_vec = self.vectorizer.transform([text_lower])
                sims = cosine_similarity(ticket_vec, self.category_matrix)[0]
                best_idx = int(sims.argmax())
                best_sim = float(sims[best_idx])

                if best_sim > 0.04:
                    category = self.categories[best_idx]
                    # Масштабируем уверенность: 0.10 -> 0.72, 0.30 -> 0.88, >0.50 -> 0.95
                    confidence = min(0.98, max(0.60, 0.65 + best_sim * 0.7))
            except Exception as e:
                logger.warning(f"Semantic similarity error: {e}")

        # 3. Базовый фолбэк по умолчанию
        if category is None:
            if self.categories:
                category = self.categories[0]
            else:
                category = "support.faq"
            confidence = 0.50

        # 4. Расчет приоритета (Priority calculation p0 - p3)
        cat_lower = category.lower()
        has_evidence = img_cnt > 0 or any(
            w in text_lower
            for w in [
                "скрин",
                "чек",
                "видео",
                "квитанция",
                "выписка",
                "доказательств",
                "proof",
                "screen",
                "<url>",
            ]
        )

        is_critical_security = any(
            w in cat_lower for w in ["security", "recovery", "взлом", "парол"]
        ) or any(
            w in text_lower
            for w in ["украли", "взлом", "сменили пароль", "чужой вход", "hacked"]
        )
        is_payment_issue = any(
            w in cat_lower for w in ["payment", "billing", "refund", "плат", "чек"]
        ) or any(
            w in text_lower
            for w in ["списались деньги", "не пришли деньги", "возврат средств", "ошибка оплаты"]
        )

        if is_critical_security or (is_payment_issue and has_evidence):
            priority = "p0"
        elif is_payment_issue or any(w in cat_lower for w in ["abuse", "scam", "cheat", "outage"]):
            priority = "p1"
        elif has_evidence or any(w in cat_lower for w in ["bug", "complaint", "tech"]):
            priority = "p2"
        else:
            priority = "p3"

        return {
            "category": category,
            "priority": priority,
            "confidence": round(float(confidence), 4),
        }

    def predict(
        self, ticket: dict[str, Any], text: str, has_evidence: bool = False
    ) -> dict[str, Any]:
        """Предсказывает категорию и приоритет для полного объекта тикета."""
        kind = str(ticket.get("kind") or "report")
        raw_refs = str(ticket.get("rule_refs_raw", "") or "")
        combined_text = f"{raw_refs} {text}".strip()
        try:
            raw_cnt = ticket.get("images_count") or ticket.get("attachments") or 0
            img_cnt = max(0, int(raw_cnt))
        except Exception:
            img_cnt = 0

        preds = self.predict_classes(
            text=combined_text, kind=kind, images_count=img_cnt
        )
        confidence = preds["confidence"]
        needs_human_conf = confidence < 0.55

        return {
            "category": preds["category"],
            "priority": preds["priority"],
            "confidence": confidence,
            "low_confidence_needs_human": needs_human_conf,
        }
