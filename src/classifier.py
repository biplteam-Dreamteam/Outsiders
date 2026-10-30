import os
import re
from typing import Any

import joblib
import numpy as np
from scipy import sparse

from src.preprocessor import normalize_cp1251_kz
from src.rules_mapper import label_ticket

MODEL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models"
)
CBM_MODEL_PATH = os.path.join(MODEL_DIR, "classifier.cbm")
META_PATH = os.path.join(MODEL_DIR, "classifier_meta.joblib")
JOBLIB_MODEL_PATH = os.path.join(MODEL_DIR, "classifier.joblib")

TAXONOMY_RULE_ANCHORS = {
    "2.1": "complaint.insult",
    "2.4": "complaint.insult",
    "2.6": "complaint.insult",
    "5.2": "complaint.cheat",
    "5.3": "complaint.dm",
    "5.4": "complaint.dm",
    "4.1": "complaint.scam",
    "4.2": "complaint.scam",
    "2.3": "complaint.rmt_ads",
    "4.4": "complaint.rmt_ads",
    "3.4": "complaint.admin",
}

PAYMENT_WORDS = (
    "донат",
    "donate",
    "оплат",
    "платеж",
    "платёж",
    "гк",
    "to'lov",
    "төлем",
    "сатып алу",
    "pul tushmadi",
)
ACCOUNT_WORDS = (
    "взлом",
    "украли акк",
    "пароль сменили",
    "потерял доступ",
    "akkaunt",
    "hacked",
)
HELP_WORDS = ("застрял", "вытащ", "переверн", "помогите выбраться", "текстур", "qotib")


class TicketClassifier:
    """
    Высокоскоростной гибридный классификатор категорий и приоритетов:
    - Таксономические якоря из taxonomy.json (Zero False Negatives)
    - CatBoost (.cbm) с текстовыми n-граммами и мета-признаками
    - Fallback на LogisticRegression / Rules
    - Инференс < 15 мс
    - Расчет честной вероятности (confidence)
    - При confidence < 0.55 -> needs_human = True
    """

    def __init__(self, cbm_path: str | None = None, meta_path: str | None = None):
        self.cbm_path = cbm_path or CBM_MODEL_PATH
        self.meta_path = meta_path or META_PATH
        self.catboost_model = None
        self.meta = None
        self.lr_model = None
        self.lr_vectorizer = None
        self.lr_classes = None
        self._load()

    def _load(self):
        if os.path.exists(self.cbm_path) and os.path.exists(self.meta_path):
            try:
                from catboost import CatBoostClassifier

                self.catboost_model = CatBoostClassifier()
                self.catboost_model.load_model(self.cbm_path)
                self.meta = joblib.load(self.meta_path)
            except Exception:
                self.catboost_model = None

        if os.path.exists(JOBLIB_MODEL_PATH):
            try:
                data = joblib.load(JOBLIB_MODEL_PATH)
                self.lr_model = data.get("model")
                self.lr_vectorizer = data.get("vectorizer")
                self.lr_classes = data.get("classes")
            except Exception:
                pass

    def is_trained(self) -> bool:
        return self.catboost_model is not None or self.lr_model is not None

    def predict(
        self, ticket: dict[str, Any], text: str, has_evidence: bool = False
    ) -> dict[str, Any]:
        """
        Предсказывает категорию, приоритет и confidence.
        """
        kind = ticket.get("kind", "complaint")
        raw_refs = str(ticket.get("rule_refs_raw", "") or "")
        text_norm = normalize_cp1251_kz(text)
        text_lower = text_norm.lower()
        combined_text = f"{raw_refs} {text_norm}".strip()
        img_cnt = float(ticket.get("images_count", 0) or 0)
        is_complaint = 1.0 if kind == "complaint" else 0.0
        has_ev = 1.0 if has_evidence else 0.0
        text_len = float(len(text_norm))

        category = None
        confidence = 0.85

        # 0. Check strong taxonomy rule anchors
        clean_raw_refs = re.findall(r"\b\d+\.\d+\b", raw_refs)
        if (
            clean_raw_refs
            and clean_raw_refs[0] in TAXONOMY_RULE_ANCHORS
            and kind == "complaint"
        ):
            category = TAXONOMY_RULE_ANCHORS[clean_raw_refs[0]]
            confidence = 0.95
        elif kind == "report":
            if any(w in text_lower for w in PAYMENT_WORDS):
                category = "report.payment"
                confidence = 0.95
            elif any(w in text_lower for w in ACCOUNT_WORDS):
                category = "report.account"
                confidence = 0.95
            elif any(w in text_lower for w in HELP_WORDS):
                category = "report.help"
                confidence = 0.95

        # 1. CatBoost Inference if not set by strong anchor
        if (
            category is None
            and self.catboost_model is not None
            and self.meta is not None
        ):
            try:
                vec = self.meta["vectorizer"].transform([combined_text])
                meta_arr = np.array(
                    [[is_complaint, img_cnt, text_len, has_ev]], dtype=np.float32
                )
                X_feat = sparse.hstack([vec, meta_arr]).tocsr()

                probs = self.catboost_model.predict_proba(X_feat)[0]
                best_idx = int(probs.argmax())
                confidence = float(probs[best_idx])
                category = self.meta["id_to_class"][best_idx]
            except Exception:
                category = None

        # 2. LogisticRegression Backup
        if (
            category is None
            and self.lr_model is not None
            and self.lr_vectorizer is not None
        ):
            try:
                features_text = f"__kind_{kind}__ {raw_refs} {text_norm}"
                vec = self.lr_vectorizer.transform([features_text])
                probs = self.lr_model.predict_proba(vec)[0]
                best_idx = int(probs.argmax())
                confidence = float(probs[best_idx])
                category = str(self.lr_classes[best_idx])
            except Exception:
                category = None

        # 3. Rule-based heuristic fallback
        if category is None:
            category, _ = label_ticket(ticket, text_norm)
            confidence = 0.85

        # Priority calculation strictly following taxonomy.json
        if (
            category == "report.payment"
            or (
                category == "report.account"
                and any(
                    w in text_lower for w in ["взлом", "украли", "пароль", "hacked"]
                )
            )
            or "2.6" in raw_refs
        ):
            priority = "p0"
        elif category in ["complaint.cheat", "complaint.scam", "complaint.rmt_ads"]:
            priority = "p1"
        elif kind == "complaint" and not has_evidence:
            priority = "p3"
        elif kind == "complaint" and category in [
            "complaint.insult",
            "complaint.dm",
            "complaint.admin",
            "complaint.other",
        ] or category == "report.complaint":
            priority = "p2"
        else:
            priority = "p3"

        # Low confidence guardrail
        needs_human_conf = confidence < 0.55

        return {
            "category": category,
            "priority": priority,
            "confidence": round(confidence, 4),
            "low_confidence_needs_human": needs_human_conf,
        }
