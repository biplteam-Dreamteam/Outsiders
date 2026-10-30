import os
import sys

sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_health():
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["classifier_loaded"] is True
    print("Health check test passed!")


def test_triage_complaint():
    payload = {
        "ticket_id": "test_complaint_01",
        "kind": "complaint",
        "created_at": "2026-03-14T19:02:00",
        "region": "kz",
        "server_lang": "kk",
        "lang": "ru",
        "reporter_hash": "user_123",
        "reported_nick": "Ivan_Petrov",
        "rule_refs_raw": "2.1",
        "images_count": 2,
        "messages": [
            {"role": "player", "text": "оскорбил меня и мою семью в чате, вот скрин"}
        ],
    }
    res = client.post("/triage", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["category"] == "complaint.insult"
    assert data["priority"] == "p2"
    assert "2.1" in data["draft_reply"]["cited"]
    assert data["needs_human"] is True  # complaint with evidence
    assert data["extracted"]["nickname"] == "Ivan_Petrov"
    print(
        "Complaint triage test passed! Category:",
        data["category"],
        "Draft cited:",
        data["draft_reply"]["cited"],
    )


def test_triage_payment_p0():
    payload = {
        "ticket_id": "test_payment_02",
        "kind": "report",
        "created_at": "2026-03-14T19:05:00",
        "region": "kz",
        "messages": [
            {"role": "player", "text": "оплатил гк, донат не пришел на аккаунт"}
        ],
    }
    res = client.post("/triage", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["category"] == "report.payment"
    assert data["priority"] == "p0"
    assert data["needs_human"] is True
    print(
        "Payment p0 test passed! Priority:",
        data["priority"],
        "Needs human:",
        data["needs_human"],
    )


def test_kazakh_normalization():
    payload = {
        "ticket_id": "test_kz_03",
        "kind": "report",
        "created_at": "2026-03-14T19:10:00",
        "region": "kz",
        "messages": [
            # cp1251 corrupted: ќ->қ, є->ә, ѕ->ң
            {
                "role": "player",
                "text": "сєлем админ, маєан кґмек керек, ќалай жґмыс жасауєа болады",
            }
        ],
    }
    res = client.post("/triage", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["lang"] == "kk"
    print("Kazakh normalization and lang detection test passed! Lang:", data["lang"])


if __name__ == "__main__":
    test_health()
    test_triage_complaint()
    test_triage_payment_p0()
    test_kazakh_normalization()
    print("\nALL UNIT TESTS PASSED SUCCESSFULLY!")
