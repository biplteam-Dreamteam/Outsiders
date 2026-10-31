import asyncio
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath("."))
from src.llm_client import LLMClient
from src.pipeline import SupportCopilotPipeline


async def test_kazakh_replies():
    print("=" * 60)
    print("Testing Multilingual Support & Kazakh Draft Generation")
    print("=" * 60)

    client = LLMClient()
    pipeline = SupportCopilotPipeline()

    # 1. Test fallback on Kazakh ticket with rule
    kz_ticket = {
        "id": "test_kz_1",
        "kind": "complaint",
        "messages": [
            {
                "role": "player",
                "text": "Маған көмек беріңізші, ойыншы дмил меня без причины у спавна",
            }
        ],
        "lang": "kk",
        "images_count": 1,
    }

    rules = [
        {
            "ref": "4.1",
            "text": "Запрещен DM (DeathMatch) — нанесение урона без причины.",
        }
    ]

    res_fallback_kz = client.generate_fallback(
        lang="kk",
        ticket=kz_ticket,
        category="complaint.player.dm",
        retrieved_rules=rules,
        nickname="Arman_Khan",
    )

    print("\n[TEST 1] Kazakh Fallback with cited rule 4.1:")
    print("Generated Text:", res_fallback_kz["text"])
    print("Cited:", res_fallback_kz["cited"])

    assert res_fallback_kz["lang"] == "kk"
    assert "4.1" in res_fallback_kz["text"]
    assert "4.1" in res_fallback_kz["cited"]
    # Verify no raw Russian rule text is embedded
    assert "Запрещен DM" not in res_fallback_kz["text"]
    print("--> PASS: 100% clean Kazakh with rule 4.1 cited!")

    # 2. Test Uzbek Fallback
    uz_ticket = {
        "id": "test_uz_1",
        "kind": "complaint",
        "messages": [
            {"role": "player", "text": "mesabab dm qildi va zz da oldirdi iltimos yordam"}
        ],
        "lang": "uz",
        "images_count": 1,
    }
    res_fallback_uz = client.generate_fallback(
        lang="uz",
        ticket=uz_ticket,
        category="complaint.player.dm",
        retrieved_rules=rules,
        nickname="Jasur_Ali",
    )

    print("\n[TEST 2] Uzbek Fallback with cited rule 4.1:")
    print("Generated Text:", res_fallback_uz["text"])
    print("Cited:", res_fallback_uz["cited"])

    assert res_fallback_uz["lang"] == "uz"
    assert "4.1" in res_fallback_uz["text"]
    assert "4.1" in res_fallback_uz["cited"]
    assert "Запрещен DM" not in res_fallback_uz["text"]
    print("--> PASS: 100% clean Uzbek with rule 4.1 cited!")

    # 3. Test Full Pipeline triage (sync & async) on Kazakh ticket
    res_pipeline_sync = pipeline.triage_ticket_sync(kz_ticket)
    print("\n[TEST 3] Pipeline Sync Triage on Kazakh Ticket:")
    print("Lang:", res_pipeline_sync["lang"])
    print("Draft reply:", res_pipeline_sync["draft_reply"])
    assert res_pipeline_sync["lang"] == "kk"
    assert res_pipeline_sync["draft_reply"]["lang"] == "kk"
    print("--> PASS: Pipeline Sync produces pure Kazakh reply!")

    res_pipeline_async = await pipeline.triage_ticket_async(kz_ticket)
    print("\n[TEST 4] Pipeline Async Triage on Kazakh Ticket:")
    print("Lang:", res_pipeline_async["lang"])
    print("Draft reply:", res_pipeline_async["draft_reply"])
    assert res_pipeline_async["lang"] == "kk"
    assert res_pipeline_async["draft_reply"]["lang"] == "kk"
    print("--> PASS: Pipeline Async produces pure Kazakh reply!")

    # 4. Test Language Validator
    assert (
        client._validate_response_lang(
            "Здравствуйте, ваше обращение принято к рассмотрению правил проекта.", "kk"
        )
        is False
    )
    assert (
        client._validate_response_lang(
            "Сәлеметсіз бе, Arman_Khan. Сіздің өтінішіңіз қабылданды.", "kk"
        )
        is True
    )
    assert (
        client._validate_response_lang(
            "Assalomu alaykum, Jasur_Ali. Murojaatingiz qabul qilindi.", "uz"
        )
        is True
    )
    assert (
        client._validate_response_lang(
            "Здравствуйте, ваше обращение принято к рассмотрению.", "uz"
        )
        is False
    )
    print("--> PASS: Language validator correctly blocks Russian leakages for kk and uz!")

    await client.aclose()
    print("\n" + "=" * 60)
    print("ALL MULTILINGUAL KAZAKH & UZBEK TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_kazakh_replies())

