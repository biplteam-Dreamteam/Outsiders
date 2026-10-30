import os
import sys
import time

import joblib
import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import train_test_split

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DATA_PATH = os.path.join("data", "train_labeled.csv")
MODEL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models"
)
os.makedirs(MODEL_DIR, exist_ok=True)

CAT_MODEL_PATH = os.path.join(MODEL_DIR, "category_model.cbm")
PRIO_MODEL_PATH = os.path.join(MODEL_DIR, "priority_model.cbm")
LEGACY_MODEL_PATH = os.path.join(MODEL_DIR, "classifier.cbm")
META_PATH = os.path.join(MODEL_DIR, "classifier_meta.joblib")


def train_models():
    print("=" * 72)
    print("🔥 TRAINING CATBOOST CLASSIFIERS (CATEGORY & PRIORITY)")
    print("=" * 72)

    if not os.path.exists(DATA_PATH):
        raise FileNotFoundError(
            f"Labeled data not found at {DATA_PATH}. Run src/prepare_dataset.py first!"
        )

    # 1. Load Data
    t0 = time.time()
    print(f"Loading {DATA_PATH}...")
    df = pd.read_csv(
        DATA_PATH,
        dtype={
            "ticket_id": str,
            "kind": str,
            "text": str,
            "images_count": int,
            "category": str,
            "priority": str,
        },
    )
    df["text"] = df["text"].fillna("")
    df["images_count"] = df["images_count"].fillna(0).astype(int)
    print(f"Loaded {len(df)} samples in {time.time() - t0:.2f}s.")

    # 2. Text Feature Extraction: char_wb (3, 5)
    print("\nExtracting TF-IDF char_wb (3, 5) n-grams...")
    t_tfidf = time.time()
    vectorizer = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(3, 5),
        max_features=25000,
        min_df=3,
        sublinear_tf=True,
    )
    X_tfidf = vectorizer.fit_transform(df["text"])
    print(f"TF-IDF Matrix shape: {X_tfidf.shape} in {time.time() - t_tfidf:.2f}s.")

    # 3. Dense / Metadata Features
    is_complaint = (df["kind"] == "complaint").astype(float).values.reshape(-1, 1)
    images_cnt = df["images_count"].values.reshape(-1, 1).astype(float)
    text_len = df["text"].str.len().values.reshape(-1, 1).astype(float)
    X_dense = np.hstack([is_complaint, images_cnt, text_len])
    X_all = sparse.hstack([X_tfidf, sparse.csr_matrix(X_dense)]).tocsr()
    print(f"Combined Feature Matrix shape: {X_all.shape}")

    # 4. Target Encodings
    cat_unique = sorted(df["category"].unique())
    prio_unique = sorted(df["priority"].unique())

    cat2id = {c: i for i, c in enumerate(cat_unique)}
    id2cat = {i: c for i, c in enumerate(cat_unique)}
    prio2id = {p: i for i, p in enumerate(prio_unique)}
    id2prio = {i: p for i, p in enumerate(prio_unique)}

    y_cat = df["category"].map(cat2id).values
    y_prio = df["priority"].map(prio2id).values

    # Train / Test Split
    print("\nSplitting into train/test sets (85% train / 15% validation)...")
    idx_train, idx_test = train_test_split(
        np.arange(len(df)), test_size=0.15, random_state=42, stratify=y_cat
    )

    X_train, X_test = X_all[idx_train], X_all[idx_test]
    y_cat_train, y_cat_test = y_cat[idx_train], y_cat[idx_test]
    y_prio_train, y_prio_test = y_prio[idx_train], y_prio[idx_test]
    print(f"Train samples: {X_train.shape[0]} | Validation samples: {X_test.shape[0]}")

    # =========================================================
    # 5. Train Model 1: Category Classifier
    # =========================================================
    print("\n" + "=" * 60)
    print("🚀 Training CatBoost for CATEGORY (14 classes)...")
    print("=" * 60)
    t_cat = time.time()
    cat_model = CatBoostClassifier(
        iterations=350,
        learning_rate=0.15,
        depth=6,
        loss_function="MultiClass",
        random_seed=42,
        thread_count=-1,
        verbose=100,
    )
    cat_model.fit(
        X_train, y_cat_train, eval_set=(X_test, y_cat_test), early_stopping_rounds=30
    )
    t_cat_train = time.time() - t_cat
    print(f"Category model training finished in {t_cat_train:.2f}s.")

    # Evaluate Category
    y_cat_pred = cat_model.predict(X_test).ravel()
    cat_acc = accuracy_score(y_cat_test, y_cat_pred)
    cat_macro_f1 = f1_score(y_cat_test, y_cat_pred, average="macro")
    print("\n📊 Category Model Validation Results:")
    print(f"   Accuracy: {cat_acc * 100:.2f}%")
    print(f"   Macro-F1: {cat_macro_f1:.4f}")

    # =========================================================
    # 6. Train Model 2: Priority Classifier
    # =========================================================
    print("\n" + "=" * 60)
    print("🚀 Training CatBoost for PRIORITY (4 classes: p0..p3)...")
    print("=" * 60)
    t_prio = time.time()
    prio_model = CatBoostClassifier(
        iterations=250,
        learning_rate=0.15,
        depth=5,
        loss_function="MultiClass",
        random_seed=42,
        thread_count=-1,
        verbose=100,
    )
    prio_model.fit(
        X_train, y_prio_train, eval_set=(X_test, y_prio_test), early_stopping_rounds=25
    )
    t_prio_train = time.time() - t_prio
    print(f"Priority model training finished in {t_prio_train:.2f}s.")

    # Evaluate Priority
    y_prio_pred = prio_model.predict(X_test).ravel()
    prio_acc = accuracy_score(y_prio_test, y_prio_pred)
    prio_macro_f1 = f1_score(y_prio_test, y_prio_pred, average="macro")
    print("\n📊 Priority Model Validation Results:")
    print(f"   Accuracy: {prio_acc * 100:.2f}%")
    print(f"   Macro-F1: {prio_macro_f1:.4f}")

    # =========================================================
    # 7. Save Models and Metadata
    # =========================================================
    print("\n" + "=" * 60)
    print("💾 Saving trained models and vectorizer to models/...")
    print("=" * 60)
    cat_model.save_model(CAT_MODEL_PATH)
    cat_model.save_model(
        LEGACY_MODEL_PATH
    )  # Maintain backward compatibility with classifier.cbm
    prio_model.save_model(PRIO_MODEL_PATH)

    meta_payload = {
        "vectorizer": vectorizer,
        "cat_classes": cat_unique,
        "cat2id": cat2id,
        "id2cat": id2cat,
        "prio_classes": prio_unique,
        "prio2id": prio2id,
        "id2prio": id2prio,
        # backward compatibility keys for legacy classifier loader
        "id_to_class": id2cat,
        "class_to_id": cat2id,
        "classes": cat_unique,
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metrics": {
            "category_accuracy": float(cat_acc),
            "category_macro_f1": float(cat_macro_f1),
            "priority_accuracy": float(prio_acc),
            "priority_macro_f1": float(prio_macro_f1),
        },
    }
    joblib.dump(meta_payload, META_PATH)
    print(f"Saved category model to: {CAT_MODEL_PATH}")
    print(f"Saved priority model to: {PRIO_MODEL_PATH}")
    print(f"Saved metadata to:       {META_PATH}")
    print(f"Total training pipeline completed in {time.time() - t0:.2f}s.")
    print("=" * 72)


if __name__ == "__main__":
    train_models()
