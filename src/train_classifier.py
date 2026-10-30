import os
import sys
import gzip
import json
import time
import numpy as np
from scipy import sparse
from collections import Counter
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import classification_report, accuracy_score, f1_score
from catboost import CatBoostClassifier
import joblib

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from src.preprocessor import normalize_cp1251_kz, extract_facts
from src.rules_mapper import label_ticket

MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")
os.makedirs(MODEL_DIR, exist_ok=True)
CBM_MODEL_PATH = os.path.join(MODEL_DIR, "classifier.cbm")
META_PATH = os.path.join(MODEL_DIR, "classifier_meta.joblib")


def load_dataset(max_records: int = 60000):
    train_file = "tickets_train.jsonl.gz"
    if not os.path.exists(train_file):
        train_file = "tickets_train.jsonl"
    if not os.path.exists(train_file):
        raise FileNotFoundError("Could not find tickets_train dataset file (.jsonl or .gz)!")

    print(f"Loading data from {train_file} (sampling up to {max_records} balanced records)...")
    opener = gzip.open(train_file, "rt", encoding="utf-8") if train_file.endswith(".gz") else open(train_file, "r", encoding="utf-8")

    texts = []
    meta_features = []
    labels = []

    c_count = 0
    r_count = 0
    target_each = max_records // 2

    # Include seed taxonomy examples
    if os.path.exists("taxonomy.json"):
        tax = json.load(open("taxonomy.json", encoding="utf-8"))
        for c in tax.get("categories", []):
            code = c["code"]
            kind = c.get("kind", "complaint")
            for ex in c.get("examples", []):
                for _ in range(15):
                    texts.append(ex)
                    meta_features.append([1.0 if kind == "complaint" else 0.0, 0.0, float(len(ex)), 0.0])
                    labels.append(code)

    with opener as f:
        for line in f:
            item = json.loads(line)
            kind = item.get("kind", "complaint")

            if kind == "complaint" and c_count >= target_each:
                continue
            if kind == "report" and r_count >= target_each:
                continue

            if kind == "complaint":
                c_count += 1
            else:
                r_count += 1

            player_msgs = [m.get("text", "") for m in item.get("messages", []) if m.get("role") == "player"]
            raw_text = " ".join(player_msgs)
            text_norm = normalize_cp1251_kz(raw_text)
            raw_refs = str(item.get("rule_refs_raw", "") or "")
            combined_text = f"{raw_refs} {text_norm}".strip()

            img_cnt = float(item.get("images_count", 0) or 0)
            is_complaint = 1.0 if kind == "complaint" else 0.0
            facts = extract_facts(item, text=text_norm, rule_refs_raw=raw_refs, images_count=int(img_cnt))
            has_ev = 1.0 if facts["has_evidence"] else 0.0
            text_len = float(len(text_norm))

            cat, _ = label_ticket(item, text_norm)

            texts.append(combined_text)
            meta_features.append([is_complaint, img_cnt, text_len, has_ev])
            labels.append(cat)

            if c_count >= target_each and r_count >= target_each:
                break

    print(f"Loaded {len(texts)} samples (complaints: {c_count}, reports: {r_count})")
    return texts, np.array(meta_features, dtype=np.float32), labels


def train_and_evaluate():
    print("=" * 65)
    print("🐱 Training CatBoost Multilingual Classifier on Grand Mobile Train")
    print("=" * 65)

    texts, meta_feats, labels = load_dataset(max_records=50000)

    # Convert string labels to integer classes
    unique_classes = sorted(list(set(labels)))
    class_to_id = {cls_name: idx for idx, cls_name in enumerate(unique_classes)}
    id_to_class = {idx: cls_name for cls_name, idx in class_to_id.items()}
    y = np.array([class_to_id[l] for l in labels], dtype=np.int32)

    # Split train/val
    from sklearn.model_selection import train_test_split
    indices = np.arange(len(texts))
    idx_train, idx_val = train_test_split(indices, test_size=0.15, random_state=42, stratify=y)

    print("\nExtracting TF-IDF text features...")
    vectorizer = TfidfVectorizer(
        ngram_range=(1, 2),
        max_features=12000,
        sublinear_tf=True,
        min_df=2
    )

    X_text_train = vectorizer.fit_transform([texts[i] for i in idx_train])
    X_text_val = vectorizer.transform([texts[i] for i in idx_val])

    # Combine text sparse matrix with metadata features
    X_train = sparse.hstack([X_text_train, meta_feats[idx_train]]).tocsr()
    X_val = sparse.hstack([X_text_val, meta_feats[idx_val]]).tocsr()
    y_train = y[idx_train]
    y_val = y[idx_val]

    print(f"Feature matrix shape: {X_train.shape}")
    print(f"Classes ({len(unique_classes)}): {unique_classes}")

    print("\nInitializing CatBoostClassifier...")
    model = CatBoostClassifier(
        iterations=300,
        learning_rate=0.15,
        depth=6,
        loss_function='MultiClass',
        random_seed=42,
        thread_count=-1,
        verbose=50
    )

    t0 = time.time()
    model.fit(X_train, y_train, eval_set=(X_val, y_val), early_stopping_rounds=30)
    dur = time.time() - t0
    print(f"\nCatBoost model trained in {dur:.2f}s!")

    # Evaluate on internal split
    val_preds = model.predict(X_val).flatten().astype(int)
    val_acc = accuracy_score(y_val, val_preds)
    val_f1 = f1_score(y_val, val_preds, average='macro')
    print("\n--- VALIDATION METRICS (Internal Split) ---")
    print(f"Accuracy:  {val_acc:.4f} ({val_acc*100:.2f}%)")
    print(f"Macro F1:  {val_f1:.4f}")

    # Save CatBoost model to CBM format
    model.save_model(CBM_MODEL_PATH)
    print(f"\nSaved CatBoost model to: {CBM_MODEL_PATH}")

    # Save Vectorizer and metadata
    meta = {
        "vectorizer": vectorizer,
        "class_to_id": class_to_id,
        "id_to_class": id_to_class,
        "classes": unique_classes,
        "accuracy": val_acc,
        "macro_f1": val_f1
    }
    joblib.dump(meta, META_PATH)
    print(f"Saved metadata to: {META_PATH}")

    # Evaluate on tickets_valid.jsonl
    if os.path.exists("tickets_valid.jsonl"):
        print("\nEvaluating on official tickets_valid.jsonl (1000 items)...")
        valid_texts = []
        valid_meta = []
        valid_ids = []
        with open("tickets_valid.jsonl", "r", encoding="utf-8") as f:
            for line in f:
                item = json.loads(line)
                p_msgs = [m.get("text", "") for m in item.get("messages", []) if m.get("role") == "player"]
                t_norm = normalize_cp1251_kz(" ".join(p_msgs))
                r_refs = str(item.get("rule_refs_raw", "") or "")
                combined = f"{r_refs} {t_norm}".strip()
                img = float(item.get("images_count", 0) or 0)
                is_comp = 1.0 if item.get("kind") == "complaint" else 0.0
                facts = extract_facts(item, text=t_norm, rule_refs_raw=r_refs, images_count=int(img))
                valid_texts.append(combined)
                valid_meta.append([is_comp, img, float(len(t_norm)), 1.0 if facts["has_evidence"] else 0.0])
                valid_ids.append(item.get("ticket_id"))

        X_valid_text = vectorizer.transform(valid_texts)
        X_valid = sparse.hstack([X_valid_text, np.array(valid_meta, dtype=np.float32)]).tocsr()

        # Measure latency
        t_start = time.perf_counter()
        probs = model.predict_proba(X_valid)
        total_lat_ms = (time.perf_counter() - t_start) * 1000.0
        avg_lat = total_lat_ms / len(valid_texts)

        preds_idx = np.argmax(probs, axis=1)
        pred_labels = [id_to_class[i] for i in preds_idx]

        print(f"Processed 1000 tickets in {total_lat_ms:.2f} ms ({avg_lat:.2f} ms/ticket)")
        print("\nTop 5 predicted categories on validation set:")
        for cat, cnt in Counter(pred_labels).most_common(5):
            print(f"  {cat}: {cnt} ({cnt/len(valid_texts)*100:.1f}%)")

    print("\nTraining and validation complete!")


if __name__ == "__main__":
    train_and_evaluate()
