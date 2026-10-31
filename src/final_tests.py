"""
Комплексный стресс-тест пайплайна Grand Mobile Support Copilot
Проверяет все 6 критических сценариев (мультиязычность, битые кодировки,
смешанные языки, Guardrails безопасности и нулевые галлюцинации).
"""

import json
import os
import sys
import time
from typing import Any

# Ensure UTF-8 output encoding in any environment
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Add project root to sys.path
sys.path.insert(0, os.path.abspath("."))

from fastapi.testclient import TestClient

from main import app
from src.preprocessor import normalize_cp1251_kz

# Load official rules to verify zero hallucinations
RULES_PATH = "rules.json"
valid_rules = json.load(open(RULES_PATH, encoding="utf-8"))
VALID_REFS = set(
    p["ref"] for r in valid_rules.get("rules", []) for p in r.get("points", [])
)


def run_stress_tests():
    print("=" * 80)
    print("🔥 GRAND MOBILE COPILOT: COMPREHENSIVE STRESS & QA TESTING 🔥")
    print("=" * 80)

    client = TestClient(app)
    results = []

    test_cases = [
        {
            "id": "CASE-1-RU",
            "name": "1. Чистый Русский (Жалоба на ДМ / ДБ машиной)",
            "input_text": "Игрок Ivan_Petrov намеренно задавил меня машиной без причины на спавне, чистый ДБ и ДМ. Вот фрапс: <url>",
            "payload": {
                "id": "stress_case_1",
                "kind": "complaint",
                "messages": [
                    {
                        "role": "player",
                        "text": "Игрок Ivan_Petrov намеренно задавил меня машиной без причины на спавне, чистый ДБ и ДМ. Вот фрапс: <url>",
                    }
                ],
                "images_count": 1,
            },
            "expected_lang": "ru",
            "expected_needs_human": True,  # Complaint with proof requires admin verdict
            "check_fn": lambda res: (
                res["lang"] == "ru"
                and res["draft_reply"]["lang"] == "ru"
                and res["needs_human"] is True
                and any(
                    dm in res["category"]
                    for dm in ("complaint.dm", "complaint.db", "complaint.player")
                )
            ),
        },
        {
            "id": "CASE-2-KK-CP1251",
            "name": "2. Казахский с битой кодировкой cp1251 (Кража аккаунта)",
            "input_text": "Меніѕ аккаунтымды ўрлап кетті, көмектесіңізші пароль ауыстырған",
            "payload": {
                "id": "stress_case_2",
                "kind": "report",
                "messages": [
                    {
                        "role": "player",
                        "text": "Меніѕ аккаунтымды ўрлап кетті, көмектесіңізші пароль ауыстырған",
                    }
                ],
            },
            "expected_lang": "kk",
            "expected_needs_human": True,  # Account security guardrail
            "check_fn": lambda res: (
                res["lang"] == "kk"
                and res["draft_reply"]["lang"] == "kk"
                and res["needs_human"] is True
                and res["priority"] in ("p0", "p1")
                and any(
                    "аккаунт" in r.lower() or "report.account" in r
                    for r in res["reasons"]
                )
            ),
        },
        {
            "id": "CASE-3-UZ",
            "name": "3. Чистый Узбекский (Пропажа машины / помощь)",
            "input_text": "Meni mashinam yo'qolib qoldi, yordam bering",
            "payload": {
                "id": "stress_case_3",
                "kind": "report",
                "messages": [
                    {
                        "role": "player",
                        "text": "Meni mashinam yo'qolib qoldi, yordam bering",
                    }
                ],
            },
            "expected_lang": "uz",
            "expected_needs_human": False,
            "check_fn": lambda res: (
                res["lang"] == "uz"
                and res["draft_reply"]["lang"] == "uz"
                and (
                    "assalomu" in res["draft_reply"]["text"].lower()
                    or "yordam" in res["draft_reply"]["text"].lower()
                    or "murojaat" in res["draft_reply"]["text"].lower()
                )
            ),
        },
        {
            "id": "CASE-4-MIXED",
            "name": "4. Смешанный сленг (RU + KK + Сленг + cp1251)",
            "input_text": "Саламалейкум админ, тут один чел меня ДМ-ил, кјмектесші пж, скрин бар",
            "payload": {
                "id": "stress_case_4",
                "kind": "complaint",
                "messages": [
                    {
                        "role": "player",
                        "text": "Саламалейкум админ, тут один чел меня ДМ-ил, кјмектесші пж, скрин бар",
                    }
                ],
                "images_count": 1,
            },
            "expected_lang": "kk",  # Dominant greeting & request is Kazakh
            "expected_needs_human": True,  # Complaint with proof
            "check_fn": lambda res: (
                res["lang"] == "kk"
                and res["draft_reply"]["lang"] == "kk"
                and res["extracted"]["has_evidence"] is True
                and res["needs_human"] is True
            ),
        },
        {
            "id": "CASE-5-GUARDRAIL",
            "name": "5. Guardrails Безопасности (Донат / Финансы - без LLM)",
            "input_text": "Сколько стоит випка? Хочу купить донат",
            "payload": {
                "id": "stress_case_5",
                "kind": "report",
                "messages": [
                    {
                        "role": "player",
                        "text": "Сколько стоит випка? Хочу купить донат",
                    }
                ],
            },
            "expected_lang": "ru",
            "expected_needs_human": True,  # Mandatory human review for financial questions
            "check_fn": lambda res: (
                res["needs_human"] is True
                and res["priority"] == "p0"
                and res["category"] == "report.payment"
                and any("финанс" in r.lower() or "донат" in r.lower() for r in res["reasons"])
                and len(res["draft_reply"]["cited"]) == 0  # Zero hallucinated rules
            ),
        },
        {
            "id": "CASE-6-EN",
            "name": "6. Английский язык (Help me flip my car, I am stuck)",
            "input_text": "Help me flip my car, I am stuck",
            "payload": {
                "id": "stress_case_6",
                "kind": "report",
                "messages": [
                    {"role": "player", "text": "Help me flip my car, I am stuck"}
                ],
            },
            "expected_lang": "en",
            "expected_needs_human": False,
            "check_fn": lambda res: (
                res["lang"] == "en"
                and res["draft_reply"]["lang"] == "en"
                and ("greetings" in res["draft_reply"]["text"].lower() or "help" in res["draft_reply"]["text"].lower())
            ),
        },
    ]

    all_passed = True

    for tc in test_cases:
        t0 = time.perf_counter()
        resp = client.post("/triage", json=tc["payload"])
        latency_ms = (time.perf_counter() - t0) * 1000.0

        if resp.status_code != 200:
            print(f"❌ {tc['name']}: HTTP {resp.status_code}")
            all_passed = False
            continue

        data = resp.json()

        # 1. Hallucination check
        cited = data.get("draft_reply", {}).get("cited", [])
        hallucinated = [c for c in cited if c not in VALID_REFS]
        has_hallucinations = len(hallucinated) > 0

        # 2. Logic check
        passes_logic = tc["check_fn"](data)

        # 3. Latency check (< 3000 ms)
        passes_latency = latency_ms < 3000.0

        is_success = passes_logic and not has_hallucinations and passes_latency
        if not is_success:
            all_passed = False

        status_str = "PASS ✅" if is_success else "FAIL ❌"

        # Log case result
        print(f"\n------------------------------------------------------------")
        print(f"🔹 {tc['name']}")
        print(f"   Input:        \"{tc['input_text']}\"")
        if tc["id"] == "CASE-2-KK-CP1251":
            print(f"   Normalized:   \"{normalize_cp1251_kz(tc['input_text'])}\"")
        print(f"   Detected:     lang={data.get('lang')} | category={data.get('category')} | priority={data.get('priority')}")
        print(f"   Guardrails:   needs_human={data.get('needs_human')} | reasons={data.get('reasons')}")
        print(f"   Draft Reply:  lang={data.get('draft_reply', {}).get('lang')} | cited={cited}")
        print(f"   Text:         \"{data.get('draft_reply', {}).get('text')}\"")
        print(f"   Performance:  latency={latency_ms:.2f} ms (< 3000 ms limit) -> {status_str}")

        results.append({
            "id": tc["id"],
            "title": tc["name"],
            "input_lang": tc["expected_lang"],
            "detected_lang": data.get("lang"),
            "category": data.get("category"),
            "priority": data.get("priority"),
            "needs_human": data.get("needs_human"),
            "cited_count": len(cited),
            "hallucinations": len(hallucinated),
            "latency_ms": latency_ms,
            "status": "PASS" if is_success else "FAIL",
        })

    # Summary Table
    print("\n" + "=" * 95)
    print("📋 SUMMARY STRESS-TEST RESULTS MATRIX")
    print("=" * 95)
    header = f"{'Case ID':<18} | {'Lang':<5} | {'Category':<18} | {'Pri':<4} | {'Human':<6} | {'Cited':<5} | {'Latency':<9} | {'Status'}"
    print(header)
    print("-" * 95)
    for r in results:
        line = (
            f"{r['id']:<18} | {r['detected_lang']:<5} | {r['category']:<18} | "
            f"{r['priority']:<4} | {str(r['needs_human']):<6} | {r['cited_count']:<5} | "
            f"{r['latency_ms']:.2f} ms | {r['status']}"
        )
        print(line)
    print("=" * 95)

    if all_passed:
        print("🏆 SUCCESS: ALL 6 CRITICAL STRESS CASES PASSED 100%! ZERO HALLUCINATIONS.")
        return 0
    else:
        print("⚠️ FAILURE: Some stress test cases failed.")
        return 1


if __name__ == "__main__":
    exit_code = run_stress_tests()
    sys.exit(exit_code)
