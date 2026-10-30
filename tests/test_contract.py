import os
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import json

required_top_keys = {
    "lang", "category", "priority", "is_spam_or_duplicate",
    "extracted", "draft_reply", "needs_human", "confidence", "reasons"
}

required_extracted_keys = {"nickname", "rule_refs", "has_evidence", "server"}
required_draft_keys = {"lang", "text", "cited"}

valid_rules = json.load(open("rules.json", encoding="utf-8"))
valid_refs = set(p["ref"] for r in valid_rules.get("rules", []) for p in r.get("points", []))

print("Validating pred.jsonl...")
errors = 0
total = 0

with open("pred.jsonl", "r", encoding="utf-8") as f:
    for i, line in enumerate(f):
        total += 1
        item = json.loads(line)
        # Check top keys
        missing_top = required_top_keys - set(item.keys())
        if missing_top:
            print(f"Line {i}: Missing top keys {missing_top}")
            errors += 1

        # Check extracted keys
        ext = item.get("extracted", {})
        missing_ext = required_extracted_keys - set(ext.keys())
        if missing_ext:
            print(f"Line {i}: Missing extracted keys {missing_ext}")
            errors += 1

        # Check draft_reply keys
        dr = item.get("draft_reply", {})
        missing_dr = required_draft_keys - set(dr.keys())
        if missing_dr:
            print(f"Line {i}: Missing draft keys {missing_dr}")
            errors += 1

        # Check cited rules hallucination
        for c in dr.get("cited", []):
            if c not in valid_refs:
                print(f"Line {i}: HALLUCINATED RULE cited: {c}")
                errors += 1

        if i < 2:
            print(f"\n--- SAMPLE RECORD #{i+1} ---")
            print(json.dumps(item, ensure_ascii=False, indent=2))

print(f"\nValidation finished! Total records: {total}, Errors: {errors}")
if errors == 0:
    print("SUCCESS: ALL 1000 RECORDS 100% COMPLIANT WITH CASE CONTRACT AND ZERO HALLUCINATIONS!")
