import json
import os
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

print("=" * 65)
print("🌐 LIVE SERVER ENDPOINT TESTING (FastAPI & Streamlit)")
print("=" * 65)

# 1. Health check
print("\n[1/3] Testing GET http://127.0.0.1:8000/health ...")
req = urllib.request.Request("http://127.0.0.1:8000/health")
with urllib.request.urlopen(req) as resp:
    health_data = json.loads(resp.read().decode("utf-8"))
    print("Health Status:", health_data)
    assert health_data.get("status") == "healthy"

# 2. Test Streamlit HTTP endpoint
print("\n[2/3] Testing GET http://127.0.0.1:8501 (Streamlit UI) ...")
req_st = urllib.request.Request("http://127.0.0.1:8501/_stcore/health")
try:
    with urllib.request.urlopen(req_st) as resp:
        st_status = resp.read().decode("utf-8")
        print("Streamlit Status:", st_status)
        assert resp.status == 200
except Exception as e:
    # Test base URL if _stcore/health not ready yet
    with urllib.request.urlopen("http://127.0.0.1:8501") as resp:
        print("Streamlit Base URL Status:", resp.status)
        assert resp.status == 200

# 3. Test POST /triage with broken cp1251 Kazakh characters
print("\n[3/3] Testing POST http://127.0.0.1:8000/triage with distorted cp1251 kz text...")
# "маєан ќомек беріѕізші ойыншы дмил меня без причины фрапс" -> normalized: "маған қомек беріңізші..."
payload = {
    "ticket_id": "live_eval_kazakh_cp1251",
    "kind": "complaint",
    "server_lang": "kk",
    "messages": [
        {
            "role": "player",
            "text": "маєан ќомек беріѕізші ойыншы дмил меня без причины у спавна фрапс: <url>",
        }
    ],
    "images_count": 1,
}

t0 = time.perf_counter()
triage_req = urllib.request.Request(
    "http://127.0.0.1:8000/triage",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)

with urllib.request.urlopen(triage_req) as resp:
    res = json.loads(resp.read().decode("utf-8"))
    latency = (time.perf_counter() - t0) * 1000.0

print(f"\nResponse successfully received in {latency:.2f} ms:")
print(json.dumps(res, indent=2, ensure_ascii=False))

# Verify schema
assert res["lang"] == "kk", "Language should be detected as kk"
assert res["category"] == "complaint.dm", "Category should be complaint.dm"
assert "5.3" in res["draft_reply"]["cited"] or "5.4" in res["draft_reply"]["cited"]
assert res["needs_human"] is True, "Complaint with evidence must need human"

print("\n" + "=" * 65)
print("✅ ALL LIVE SERVER TESTS COMPLETED AND VERIFIED 100%!")
print("=" * 65)

