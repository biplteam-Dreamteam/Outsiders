import os
import sys
import gzip
import json
import time
import joblib
from collections import Counter
from sklearn.model_selection import train_test_split
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, accuracy_score, f1_score

from src.preprocessor import normalize_cp1251_kz
from src.rules_mapper import label_ticket

MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
os.makedirs(MODEL_DIR, exist_ok=True)
MODEL_PATH = os.path.join(MODEL_DIR, "classifier.joblib")


def main():
    print("=" * 60)
    print("Grand Mobile Support Copilot — Classifier Training")
    print("=" * 60)

    # 1. Load taxonomy examples first
    taxonomy_path = "taxonomy.json"
    train_texts = []
    train_labels = []

    if os.path.exists(taxonomy_path):
        tax = json.load(open(taxonomy_path, encoding="utf-8"))
        for c in tax.get("categories", []):
            code = c["code"]
            kind = c.get("kind", "complaint")
            for ex in c.get("examples", []):
                # Oversample official examples
                for _ in range(10):
                    train_texts.append(f"__kind_{kind}__ {ex}")
                    train_labels.append(code)

    print(f"Loaded {len(train_texts)} seed examples from taxonomy.json")

    # 2. Sample from tickets_train.jsonl.gz
    train_file = "tickets_train.jsonl.gz"
    if not os.path.exists(train_file):
        print(f"File {train_file} not found!")
        return

    complaint_target = 25000
    report_target = 25000
    c_count = 0
    r_count = 0

    print("Sampling from tickets_train.jsonl.gz (up to 50k balanced records)...")
    start_time = time.time()

    with gzip.open(train_file, "rt", encoding="utf-8") as f:
        for line in f:
            item = json.loads(line)
            kind = item.get("kind", "complaint")

            if kind == "complaint" and c_count >= complaint_target:
                continue
            if kind == "report" and r_count >= report_target:
                continue

            if kind == "complaint":
                c_count += 1
            else:
                r_count += 1

            msgs = " ".join([m.get("text", "") for m in item.get("messages", []) if m.get("role") == "player"])
            text_norm = normalize_cp1251_kz(msgs)
            raw_refs = str(item.get("rule_refs_raw", "") or "")
            cat, _ = label_ticket(item, text_norm)

            train_texts.append(f"__kind_{kind}__ {raw_refs} {text_norm}")
            train_labels.append(cat)

            if c_count >= complaint_target and r_count >= report_target:
                break

    print(f"Loaded {len(train_texts)} total records in {time.time() - start_time:.2f}s")
    print("Class distribution:")
    for cat, cnt in Counter(train_labels).most_common():
        print(f"  {cat}: {cnt}")

    # 3. Train-Test Split
    X_train, X_val, y_train, y_val = train_test_split(
        train_texts, train_labels, test_size=0.15, random_state=42, stratify=train_labels
    )

    print("\nVectorizing features (TF-IDF)...")
    vectorizer = TfidfVectorizer(
        ngram_range=(1, 2),
        min_df=2,
        max_features=40000,
        sublinear_tf=True
    )
    X_train_vec = vectorizer.fit_transform(X_train)
    X_val_vec = vectorizer.transform(X_val)

    print("Training LogisticRegression classifier (fast & calibrated)...")
    model = LogisticRegression(
        C=2.5,
        max_iter=300,
        class_weight="balanced",
        solver="lbfgs"
    )
    t0 = time.time()
    model.fit(X_train_vec, y_train)
    train_dur = time.time() - t0
    print(f"Model trained in {train_dur:.2f}s")

    # 4. Evaluation
    y_pred = model.predict(X_val_vec)
    acc = accuracy_score(y_val, y_pred)
    f1_macro = f1_score(y_val, y_pred, average="macro")

    print("\n--- VALIDATION METRICS ---")
    print(f"Accuracy:  {acc:.4f} ({acc*100:.2f}%)")
    print(f"Macro F1:  {f1_macro:.4f}")
    print("\nClassification Report:")
    print(classification_report(y_val, y_pred, digits=4))

    # 5. Measure latency per item
    sample_text = X_val[:100]
    t0 = time.time()
    for s in sample_text:
        v = vectorizer.transform([s])
        _ = model.predict_proba(v)
    elapsed = (time.time() - t0) / 100 * 1000
    print(f"Latency per ticket: {elapsed:.2f} ms (Target: < 15 ms)")

    # 6. Save model bundle
    save_obj = {
        "model": model,
        "vectorizer": vectorizer,
        "classes": model.classes_,
        "metrics": {"accuracy": acc, "macro_f1": f1_macro, "latency_ms": elapsed}
    }
    joblib.dump(save_obj, MODEL_PATH)
    print(f"\nModel saved successfully to {MODEL_PATH}")


if __name__ == "__main__":
    main()
