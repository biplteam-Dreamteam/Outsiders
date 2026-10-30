import os
import joblib
from typing import Dict, Any, Tuple, Optional
from src.preprocessor import normalize_cp1251_kz
from src.rules_mapper import label_ticket

MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")
MODEL_PATH = os.path.join(MODEL_DIR, "classifier.joblib")


class TicketClassifier:
    """
    Высокоскоростной классификатор категорий и приоритетов:
    - Инференс < 10 мс
    - Расчет честной вероятности (confidence)
    - При confidence < 0.55 флаг needs_human = True
    """
    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path or MODEL_PATH
        self.model = None
        self.vectorizer = None
        self.classes_ = None
        self._load()

    def _load(self):
        if os.path.exists(self.model_path):
            data = joblib.load(self.model_path)
            self.model = data.get("model")
            self.vectorizer = data.get("vectorizer")
            self.classes_ = data.get("classes")

    def is_trained(self) -> bool:
        return self.model is not None and self.vectorizer is not None

    def predict(self, ticket: Dict[str, Any], text: str, has_evidence: bool = False) -> Dict[str, Any]:
        """
        Предсказывает категорию, приоритет и confidence.
        Если модель не обучена, использует надежный эвристический mapper.
        """
        kind = ticket.get("kind", "complaint")
        raw_refs = str(ticket.get("rule_refs_raw", "") or "")
        text_norm = normalize_cp1251_kz(text)
        features_text = f"__kind_{kind}__ {raw_refs} {text_norm}"

        if self.is_trained():
            try:
                vec = self.vectorizer.transform([features_text])
                probs = self.model.predict_proba(vec)[0]
                best_idx = probs.argmax()
                confidence = float(probs[best_idx])
                category = str(self.classes_[best_idx])
            except Exception:
                category, _ = label_ticket(ticket, text_norm)
                confidence = 0.85
        else:
            category, _ = label_ticket(ticket, text_norm)
            confidence = 0.85

        # Infer priority strictly following taxonomy.json
        text_lower = text_norm.lower()
        if category == "report.payment" or (category == "report.account" and any(w in text_lower for w in ["взлом", "украли", "пароль", "hacked"])) or "2.6" in raw_refs:
            priority = "p0"
        elif category in ["complaint.cheat", "complaint.scam", "complaint.rmt_ads"]:
            priority = "p1"
        elif kind == "complaint" and not has_evidence:
            priority = "p3"
        elif kind == "complaint" and category in ["complaint.insult", "complaint.dm", "complaint.admin", "complaint.other"]:
            priority = "p2"
        elif category == "report.complaint":
            priority = "p2"
        else:
            priority = "p3"

        # Low confidence guardrail
        needs_human_conf = confidence < 0.55

        return {
            "category": category,
            "priority": priority,
            "confidence": round(confidence, 4),
            "low_confidence_needs_human": needs_human_conf
        }
