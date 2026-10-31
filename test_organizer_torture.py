"""
ORGANIZER BRUTAL ROAST SUITE (99% ELIMINATION FILTER)
Decentrathon 6.0 — Case 03: Grand Mobile Support Copilot

Тестирует систему на самые коварные, сломанные, ядовитые и пограничные тикеты:
1. Пустые и битые тикеты (Empty JSON, no messages, empty text, whitespace only)
2. Нестандартные схемы (attachments вместо images_count, null во всех полях, лишние поля)
3. Попытки галлюцинаций (Выдуманные правила 99.99, 77.7, 100.500, 0.1)
4. Запрещенные обещания разбана / возврата средств без админа
5. CP1251 кракозябры и языковые смеси (kk, uz, en, ru)
6. Критические категории (донат, взлом, жалоба на админа — обязательный needs_human)
7. Дедупликация и спам-флуд (5+ тикетов в час)
8. Битые типы данных (отрицательные числа, строки вместо массивов)
"""

import sys
import os
import orjson

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath("."))
from src.pipeline import SupportCopilotPipeline
from src.rag_engine import RuleValidator

def load_rules_and_tax():
    with open("rules.json", "rb") as f:
        r_data = orjson.loads(f.read())
    valid_rules = set()
    for cat in r_data.get("rules", []):
        for pt in cat.get("points", []):
            ref = str(pt.get("ref", "")).strip()
            if ref:
                valid_rules.add(ref)

    with open("taxonomy.json", "rb") as f:
        t_data = orjson.loads(f.read())
    valid_categories = {c["code"] for c in t_data.get("categories", [])}
    valid_priorities = {p["code"] for p in t_data.get("priorities", [])}
    needs_human_always = set(t_data.get("needs_human_always", []))
    return valid_rules, valid_categories, valid_priorities, needs_human_always

def validate_contract(resp: dict, test_name: str, valid_rules, valid_categories, valid_priorities):
    req_keys = ["lang", "category", "priority", "is_spam_or_duplicate", "extracted", "draft_reply", "needs_human", "confidence", "reasons"]
    for k in req_keys:
        if k not in resp:
            raise AssertionError(f"[{test_name}] ОШИБКА КОНТРАКТА: Отсутствует ключ '{k}' в ответе!")

    if resp["lang"] not in {"ru", "kk", "uz", "en", "und"}:
        raise AssertionError(f"[{test_name}] ОШИБКА: Недопустимый язык '{resp['lang']}'")

    if resp["category"] not in valid_categories:
        raise AssertionError(f"[{test_name}] ОШИБКА: Категория '{resp['category']}' не существует в taxonomy.json!")

    if resp["priority"] not in valid_priorities:
        raise AssertionError(f"[{test_name}] ОШИБКА: Приоритет '{resp['priority']}' не существует в taxonomy.json!")

    if not isinstance(resp["is_spam_or_duplicate"], bool):
        raise AssertionError(f"[{test_name}] ОШИБКА: is_spam_or_duplicate должен быть bool!")

    extracted = resp["extracted"]
    for k in ["nickname", "rule_refs", "has_evidence", "server"]:
        if k not in extracted:
            raise AssertionError(f"[{test_name}] ОШИБКА: В extracted отсутствует ключ '{k}'!")

    for r in extracted["rule_refs"]:
        if r not in valid_rules:
            raise AssertionError(f"[{test_name}] ДИСКВАЛИФИКАЦИЯ: Галлюцинация правила в extracted.rule_refs: '{r}'!")

    draft = resp["draft_reply"]
    for k in ["lang", "text", "cited"]:
        if k not in draft:
            raise AssertionError(f"[{test_name}] ОШИБКА: В draft_reply отсутствует ключ '{k}'!")

    if draft["lang"] not in {"ru", "kk", "uz", "en"}:
        raise AssertionError(f"[{test_name}] ОШИБКА: draft_reply.lang недопустим: '{draft['lang']}'")

    if not draft["text"]:
        raise AssertionError(f"[{test_name}] ОШИБКА: Пустой текст черновика ответа!")

    for c in draft["cited"]:
        if c not in valid_rules:
            raise AssertionError(f"[{test_name}] ДИСКВАЛИФИКАЦИЯ (0% Tolerance): Галлюцинация правила в draft_reply.cited: '{c}'!")

    if not isinstance(resp["needs_human"], bool):
        raise AssertionError(f"[{test_name}] ОШИБКА: needs_human должен быть bool!")

    if not (0.0 <= resp["confidence"] <= 1.0):
        raise AssertionError(f"[{test_name}] ОШИБКА: confidence вне диапазона [0.0, 1.0]: {resp['confidence']}")

    if not isinstance(resp["reasons"], list):
        raise AssertionError(f"[{test_name}] ОШИБКА: reasons должен быть списком!")

    if resp["needs_human"] and len(resp["reasons"]) == 0:
        raise AssertionError(f"[{test_name}] ОШИБКА: needs_human=True, но список reasons пуст!")

def run_brutal_roast():
    print("=" * 80)
    print("🔥 ОРГАНИЗАТОРСКИЙ СТРЕСС-ТЕСТ (BRUTAL ROAST & CHAOS INJECTION)")
    print("🎯 Цель: отсеять 99% слабых команд и проверить устойчивость к любым сбоям")
    print("=" * 80)

    valid_rules, valid_categories, valid_priorities, needs_human_always = load_rules_and_tax()
    pipeline = SupportCopilotPipeline()

    tests = [
        # 1. Пустые и битые тикеты
        ("TEST_EMPTY_DICT", {}),
        ("TEST_NO_MESSAGES", {"ticket_id": "err_1", "kind": "complaint"}),
        ("TEST_EMPTY_MESSAGES_LIST", {"ticket_id": "err_2", "messages": []}),
        ("TEST_EMPTY_TEXT", {"ticket_id": "err_3", "messages": [{"role": "player", "text": ""}]}),
        ("TEST_WHITESPACE_ONLY", {"ticket_id": "err_4", "messages": [{"role": "player", "text": "   \n\t  \r  "}]}),
        
        # 2. Нестандартные схемы и типы
        ("TEST_ATTACHMENTS_SCHEMA", {
            "kind": "complaint",
            "messages": [{"role": "player", "text": "Arman_Petrov оскорблял меня и мою семью в чате, скрины есть, 2.1 ОП"}],
            "attachments": 2
        }),
        ("TEST_NULL_FIELDS", {
            "ticket_id": None, "kind": None, "created_at": None, "region": None,
            "server_lang": None, "lang": None, "reporter_hash": None, "reported_hash": None,
            "reported_nick": None, "rule_refs_raw": None, "images_count": None, "messages": None
        }),
        ("TEST_NEGATIVE_ATTACHMENTS", {
            "kind": "complaint",
            "messages": [{"role": "player", "text": "ДМ у банка Vasya_Pupkin"}],
            "images_count": -99,
            "attachments": -500
        }),
        ("TEST_UNEXPECTED_EXTRA_KEYS", {
            "kind": "report",
            "messages": [{"role": "player", "text": "как устроиться на работу"}],
            "unknown_admin_token": "secret_key_12345",
            "sql_injection_payload": "'; DROP TABLE tickets; --"
        }),

        # 3. Атака галлюцинациями (Выдуманные пункты правил)
        ("TEST_FAKE_RULE_IN_TEXT", {
            "kind": "complaint",
            "messages": [{"role": "player", "text": "Игрок Kolya_Sidorov нарушил вымышленное правило 99.99 и 77.7, требую забанить"}],
            "reported_nick": "Kolya_Sidorov"
        }),
        ("TEST_FAKE_RULE_IN_RAW_REFS", {
            "kind": "complaint",
            "messages": [{"role": "player", "text": "чит аим скрин <url>"}],
            "rule_refs_raw": "99.99, 100.500, 77.7",
            "images_count": 1
        }),

        # 4. Проверка запрещенных обещаний разбана / возврата денег
        ("TEST_UNBAN_REQUEST", {
            "kind": "report",
            "messages": [{"role": "player", "text": "Снимите бан пожалуйста, бан ошибочный, разбаньте меня"}],
        }),
        ("TEST_REFUND_REQUEST", {
            "kind": "report",
            "messages": [{"role": "player", "text": "Меня обманули на авторынке, верните мои 500000 рублей и машину"}],
        }),

        # 5. Кракозябры cp1251 и казахский язык
        ("TEST_KZ_CP1251_KRAKOZYABRAS", {
            "kind": "report",
            "messages": [{"role": "player", "text": "‘јлеметсіз бе! Ќандай ереже бҧзылды? Ѓаламтор ґажайып кљмек керек"}],
            "region": "kz",
            "server_lang": "kk"
        }),
        ("TEST_KZ_PURE_LITERARY_COMPLAINT", {
            "kind": "complaint",
            "messages": [{"role": "player", "text": "Серверде читер бар, ақшамды ұрлап кетті, шағым түсіремін дәлел бар"}],
            "images_count": 1,
            "region": "kz"
        }),

        # 6. Узбекский язык с апострофами
        ("TEST_UZ_APOSTROPHES_COMPLAINT", {
            "kind": "complaint",
            "messages": [{"role": "player", "text": "Salom aka, menga yordam bering iltimos, moshinam buzilib qoldi o'yin ochilmayapti"}],
            "server_lang": "uz"
        }),

        # 7. Критические Guardrails (Обязательный Human-in-the-Loop)
        ("TEST_PAYMENT_ALWAYS_HUMAN", {
            "kind": "report",
            "messages": [{"role": "player", "text": "Донат не пришел, с карты списали 2000 рублей, чек прикрепил"}],
            "images_count": 1
        }),
        ("TEST_HACK_ALWAYS_HUMAN", {
            "kind": "report",
            "messages": [{"role": "player", "text": "Взломали аккаунт, сменили пароль и почту, помогите вернуть"}],
        }),
        ("TEST_ADMIN_COMPLAINT_ALWAYS_HUMAN", {
            "kind": "complaint",
            "messages": [{"role": "player", "text": "Администратор Ivan_Ivanov выдал мне мут без причины"}],
        }),

        # 8. Длинный текст и эмодзи-флуд
        ("TEST_EMOJI_AND_LONG_TEXT", {
            "kind": "report",
            "messages": [{"role": "player", "text": "🚗💥💀🚨 " * 50 + "помогите баг застрял в автосалоне"}],
        }),
    ]

    passed_count = 0
    total_tests = len(tests)

    for name, ticket_payload in tests:
        try:
            resp = pipeline.triage_ticket_sync(ticket_payload)
            validate_contract(resp, name, valid_rules, valid_categories, valid_priorities)

            # Дополнительные жесткие проверки для конкретных сценариев
            if "FAKE_RULE" in name:
                for c in resp["draft_reply"]["cited"]:
                    assert c not in ["99.99", "77.7", "100.500"], f"[{name}] Найдено выдуманное правило {c} в cited!"
                for r in resp["extracted"]["rule_refs"]:
                    assert r not in ["99.99", "77.7", "100.500"], f"[{name}] Найдено выдуманное правило {r} в rule_refs!"
                assert resp["needs_human"] is True, f"[{name}] Атака вымышленными правилами обязана требовать человека!"

            if "KZ" in name:
                assert resp["lang"] == "kk" or resp["draft_reply"]["lang"] == "kk", f"[{name}] Не распознан казахский язык!"
                if resp["draft_reply"]["lang"] == "kk":
                    assert any(w in resp["draft_reply"]["text"] for w in ["Сәлеметсіз", "өтінішіңіз", "тексеру", "шаралар", "рахмет"]), f"[{name}] Черновик не на литературном казахском!"

            if "UZ" in name:
                assert resp["lang"] == "uz" or resp["draft_reply"]["lang"] == "uz", f"[{name}] Не распознан узбекский язык!"
                if resp["draft_reply"]["lang"] == "uz":
                    assert any(w in resp["draft_reply"]["text"] for w in ["Assalomu", "murojaat", "qabul", "choralar"]), f"[{name}] Черновик не на литературном узбекском!"

            if "ALWAYS_HUMAN" in name or "UNBAN" in name or "REFUND" in name:
                assert resp["needs_human"] is True, f"[{name}] needs_human обязан быть True!"

            print(f"  ✅ [PASS] {name:<35} -> cat: {resp['category']:<18} | prio: {resp['priority']} | human: {resp['needs_human']} | cited: {resp['draft_reply']['cited']}")
            passed_count += 1
        except Exception as e:
            print(f"  ❌ [FAIL] {name:<35} -> {e}")
            raise e

    # 9. Проверка дедупликатора (Бонус 1: 1 игрок, 1 проблема, 5 тикетов/час)
    print("-" * 80)
    print("🛡️ Проверка Бонуса №1 (Дедупликация и Анти-спам)...")
    pipeline.deduplicator.reset()

    # 9a. Проверка дубликата по схожести текста (> 85%)
    ticket_dup1 = {
        "ticket_id": "dup_1",
        "reporter_hash": "player_dup_123",
        "messages": [{"role": "player", "text": "Застрял в текстурах около банка, помогите вытащить!"}]
    }
    ticket_dup2 = {
        "ticket_id": "dup_2",
        "reporter_hash": "player_dup_123",
        "messages": [{"role": "player", "text": "Застрял в текстурах около банка, помогите вытащить!"}]
    }
    resp1 = pipeline.triage_ticket_sync(ticket_dup1)
    resp2 = pipeline.triage_ticket_sync(ticket_dup2)
    assert resp1["is_spam_or_duplicate"] is False, "Первый тикет не является дубликатом!"
    assert resp2["is_spam_or_duplicate"] is True, "Второй идентичный тикет обязан быть признан дубликатом!"
    assert resp2["needs_human"] is True, "Дубликат должен требовать внимания/закрытия!"
    print("  ✅ [PASS] Текстовый дубликат успешно распознан (RapidFuzz match > 85%)")

    # 9b. Проверка флуда (>= 5 тикетов от одного игрока за 1 час)
    pipeline.deduplicator.reset()
    rep_hash = "malicious_flooder_hash_777"
    distinct_questions = [
        "Где находится автосалон высокого класса?",
        "Как устроиться на работу в полицию?",
        "Сколько стоит номер в отеле в центре города?",
        "Где получить водительские права категории B?",
        "Какой максимальный уровень прокачки персонажа?",
        "Где купить канистру с бензином для машины?",
    ]
    for idx, q_text in enumerate(distinct_questions, start=1):
        flood_ticket = {
            "ticket_id": f"flood_{idx}",
            "reporter_hash": rep_hash,
            "messages": [{"role": "player", "text": q_text}]
        }
        resp = pipeline.triage_ticket_sync(flood_ticket)
        if idx <= 5:
            assert resp["is_spam_or_duplicate"] is False, f"Тикет #{idx} (допустимый лимит 5) не должен быть помечен как спам!"
        else:
            assert resp["is_spam_or_duplicate"] is True, f"Тикет #{idx} обязан быть помечен как спам (превышение лимита 5 тикетов/час)!"
            assert resp["needs_human"] is True, f"Спам-тикет обязан передаваться человеку!"
            print(f"  ✅ [PASS] Флуд-тикет #{idx} успешно распознан как СПАМ (превышение 5 тикетов/час)")

    print("=" * 80)
    print(f"🏆 ВСЕ {passed_count}/{total_tests} СТРЕСС-ТЕСТОВ ОРГАНИЗАТОРА УСПЕШНО ПРОЙДЕНЫ!")
    print("🚀 Решение выдержало самую жесткую прожарку без единого сбоя, галлюцинации или нарушения контракта!")
    print("=" * 80)

if __name__ == "__main__":
    run_brutal_roast()
