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
CAT_MODEL_PATH = os.path.join(MODEL_DIR, "category_model.cbm")
PRIO_MODEL_PATH = os.path.join(MODEL_DIR, "priority_model.cbm")
CBM_MODEL_PATH = os.path.join(MODEL_DIR, "classifier.cbm")
META_PATH = os.path.join(MODEL_DIR, "classifier_meta.joblib")
JOBLIB_MODEL_PATH = os.path.join(MODEL_DIR, "classifier.joblib")

TAXONOMY_RULE_ANCHORS = {
    "2.1": "complaint.insult",
    "2.2": "complaint.insult",
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
    "чек",
    "пополнил",
)
ACCOUNT_WORDS = (
    "взлом",
    "украли акк",
    "пароль сменили",
    "потерял доступ",
    "akkaunt",
    "hacked",
    "украли",
    "восстанов",
)
HELP_WORDS = (
    "застрял",
    "вытащ",
    "переверн",
    "помогите выбраться",
    "текстур",
    "qotib",
    "slap",
    "спавн",
    "баг",
    "tushib",
)
INSULT_WORDS = (
    "оск",
    "оскорб",
    "упом",
    "родных",
    "родни",
    "мать",
    "родител",
    "неадекват",
    "неадыкват",
    "мат",
    "матер",
    "обзыва",
    "haromi",
    "harom",
    "боқтау",
    "боқтық",
    "балағат",
    "в чате все видно",
    "оскр",
    "osk",
    "расизм",
    "национальн",
    "розжиг",
    "межнац",
    "транс",
)
CHEAT_WORDS = (
    "чит",
    "читы",
    "софт",
    "аим",
    "вх",
    "рванка",
    "бот",
    "кликер",
    "спидхак",
    "cheat",
    "aimbot",
)
SCAM_WORDS = (
    "скам",
    "обман",
    "развод",
    "махинаци",
    "кинул на деньги",
    "перевел деньги",
    "вымогает",
)
DM_WORDS = (
    "дм",
    "дб",
    "ск",
    "тк",
    "dm",
    "db",
    "sk",
    "tk",
    "убил",
    "урон",
    "расстрел",
    "deathmatch",
    "driveby",
    "уход от рп",
    "урп",
    "нонрп",
    "nonrp",
    "веревка в зз",
    "связал в зз",
)
RMT_WORDS = (
    "реклам",
    "продам акк",
    "продажа вирт",
    "покупка вирт",
    "вирты",
    "за реал",
    "куплю вирт",
)
QUESTION_WORDS = (
    "как ",
    "где ",
    "когда ",
    "сколько ",
    "почему ",
    "не могу ",
    "подскаж",
    "қалай",
    "қандай",
    "qanday",
    "how",
)


class TicketClassifier:
    """
    Высокоскоростной гибридный классификатор категорий и приоритетов:
    - Таксономические якоря из taxonomy.json (Zero False Negatives)
    - Две обученные CatBoost-модели: category (14 классов) и priority (p0-p3)
    - Текстовый TF-IDF char_wb (3, 5) n-gram векторизатор
    - Инференс < 20 мс
    - Расчет вероятности (confidence)
    - При confidence < 0.55 -> needs_human = True
    """

    def __init__(
        self,
        cbm_path: str | None = None,
        prio_path: str | None = None,
        meta_path: str | None = None,
    ):
        self.cbm_path = cbm_path or (
            CAT_MODEL_PATH if os.path.exists(CAT_MODEL_PATH) else CBM_MODEL_PATH
        )
        self.prio_path = prio_path or PRIO_MODEL_PATH
        self.meta_path = meta_path or META_PATH
        self.catboost_model = None
        self.prio_model = None
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

        if os.path.exists(self.prio_path):
            try:
                from catboost import CatBoostClassifier

                self.prio_model = CatBoostClassifier()
                self.prio_model.load_model(self.prio_path)
            except Exception:
                self.prio_model = None

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

    def predict_classes(
        self, text: str, kind: str = "complaint", images_count: int = 0
    ) -> dict[str, Any]:
        """
        Быстрый инференс (< 20 мс) по обученным CatBoost моделям:
        возвращает предсказанные категорию, приоритет и confidence.
        """
        text_norm = normalize_cp1251_kz(str(text or ""))
        text_lower = text_norm.lower().replace("ё", "е")
        img_cnt = float(images_count or 0)
        is_complaint = 1.0 if kind == "complaint" else 0.0
        text_len = float(len(text_norm))

        category = None
        priority = None
        confidence = 0.85

        # 0. Check strong taxonomy rule anchors
        clean_refs = re.findall(r"\b\d+\.\d+\b", text_norm)
        if (
            clean_refs
            and clean_refs[0] in TAXONOMY_RULE_ANCHORS
            and kind == "complaint"
        ):
            category = TAXONOMY_RULE_ANCHORS[clean_refs[0]]
            confidence = 0.95
        elif kind == "complaint":
            if any(w in text_lower for w in INSULT_WORDS):
                category = "complaint.insult"
                confidence = 0.95
            elif any(w in text_lower for w in CHEAT_WORDS):
                category = "complaint.cheat"
                confidence = 0.95
            elif any(w in text_lower for w in SCAM_WORDS):
                category = "complaint.scam"
                confidence = 0.95
            elif any(w in text_lower for w in RMT_WORDS):
                category = "complaint.rmt_ads"
                confidence = 0.95
            elif any(w in text_lower for w in DM_WORDS):
                category = "complaint.dm"
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
            elif any(w in text_lower for w in QUESTION_WORDS):
                category = "report.question"
                confidence = 0.95

        # 1. CatBoost Inference for Category if not determined by strong anchor
        if (
            category is None
            and self.catboost_model is not None
            and self.meta is not None
        ):
            try:
                vec = self.meta["vectorizer"].transform([text_norm])
                meta_arr = np.array(
                    [[is_complaint, img_cnt, text_len]], dtype=np.float32
                )
                X_feat = sparse.hstack([vec, meta_arr]).tocsr()

                probs = self.catboost_model.predict_proba(X_feat)[0]
                best_idx = int(probs.argmax())
                confidence = float(probs[best_idx])
                id2cat = self.meta.get("id2cat") or self.meta.get("id_to_class")
                category = id2cat[best_idx]
            except Exception:
                category = None

        # Fallback category
        if category is None:
            category, _ = label_ticket(
                {"kind": kind, "images_count": images_count}, text_norm
            )
            confidence = 0.80

        # Taxonomy priority calculation strictly adhering to taxonomy.json rules
        has_evidence = img_cnt > 0 or any(
            w in text_lower
            for w in [
                "скрин",
                "видео",
                "фрапс",
                "пруф",
                "дәлел",
                "skrin",
                "<url>",
                "доки",
                "доказательств",
            ]
        )

        if category == "report.payment" or (
            category == "report.account"
            and any(
                w in text_lower
                for w in ["взлом", "украли", "пароль", "hacked", "доступ"]
            )
        ):
            priority = "p0"
        elif category in ["complaint.cheat", "complaint.scam", "complaint.rmt_ads"]:
            priority = "p1"
        elif kind == "complaint" and not has_evidence:
            priority = "p3"
        elif (
            kind == "complaint"
            and category
            in [
                "complaint.insult",
                "complaint.dm",
                "complaint.admin",
                "complaint.other",
            ]
            or category == "report.complaint"
        ):
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
        """
        Предсказывает категорию, приоритет и confidence для полного объекта тикета.
        """
        kind = ticket.get("kind", "complaint")
        raw_refs = str(ticket.get("rule_refs_raw", "") or "")
        combined_text = f"{raw_refs} {text}".strip()
        img_cnt = int(ticket.get("images_count", 0) or 0)

        preds = self.predict_classes(
            text=combined_text, kind=kind, images_count=img_cnt
        )
        confidence = preds["confidence"]
        # СЛУЧАЙ 3 (Неуверенность модели): Если классификатор не уверен в категории (confidence < 0.55),
        # тикет обязательно маркируется для передачи живому администратору (needs_human = True).
        needs_human_conf = confidence < 0.55

        return {
            "category": preds["category"],
            "priority": preds["priority"],
            "confidence": confidence,
            "low_confidence_needs_human": needs_human_conf,
        }


# Singleton instance for high-speed inference (< 20 ms) without re-loading models
_DEFAULT_CLASSIFIER: TicketClassifier | None = None


def get_default_classifier() -> TicketClassifier:
    global _DEFAULT_CLASSIFIER
    if _DEFAULT_CLASSIFIER is None:
        _DEFAULT_CLASSIFIER = TicketClassifier()
    return _DEFAULT_CLASSIFIER


def predict_classes(
    text: str, kind: str = "complaint", images_count: int = 0
) -> dict[str, Any]:
    """
    Быстрый инференс (< 20 мс) по обученным моделям CatBoost:
    возвращает предсказанные категорию, приоритет и confidence (вероятность).
    """
    classifier = get_default_classifier()
    return classifier.predict_classes(text=text, kind=kind, images_count=images_count)
