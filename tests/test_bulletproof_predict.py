import os
import sys

sys.path.insert(0, os.path.abspath("."))
import orjson

from src.predict import main

def test_bulletproof():
    tmp_in = "test_corrupt.jsonl"
    tmp_out = "test_corrupt_out.jsonl"

    lines = [
        '{"ticket_id": "good1", "kind": "report", "messages": [{"role": "player", "text": "help stuck"}]}',
        'THIS IS NOT A VALID JSON LINE',
        '',
        '{"ticket_id": "good2", "kind": "complaint", "reported_nick": "Cheater", "messages": [{"role": "player", "text": "he is flying"}]}',
        '{"broken": true, missing_closing_brace',
    ]

    with open(tmp_in, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    sys.argv = ["predict.py", "--in", tmp_in, "--out", tmp_out]
    main()

    records = [orjson.loads(line) for line in open(tmp_out, "rb")]
    print(f"\nTotal output records: {len(records)}")
    for i, r in enumerate(records):
        print(f"Record #{i+1}: category={r['category']} | needs_human={r['needs_human']} | reasons={r['reasons']}")

    assert len(records) == 4, f"Expected 4 records, got {len(records)}"
    assert records[1]["needs_human"] is True
    assert records[3]["needs_human"] is True
    print("\n✅ BULLETPROOF TEST PASSED: No crash on malformed lines, safe fallbacks recorded!")

    if os.path.exists(tmp_in):
        os.remove(tmp_in)
    if os.path.exists(tmp_out):
        os.remove(tmp_out)

if __name__ == "__main__":
    test_bulletproof()
