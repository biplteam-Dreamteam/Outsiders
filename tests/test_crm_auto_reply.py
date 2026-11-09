import asyncio
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath("."))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from src.crm_connectors import CRMConnectorManager


class TestCRMConnectors(unittest.TestCase):
    def setUp(self):
        self.manager = CRMConnectorManager({
            "auto_reply_enabled": True,
            "min_confidence_auto_reply": 0.70,
            "allowed_auto_reply_categories": [
                "report.question",
                "report.help",
                "report.complaint",
                "report.offtopic",
                "complaint.invalid",
            ],
            "generic_webhook": {"enabled": True},
            "telegram": {"enabled": False},
            "zendesk": {"enabled": False},
        })

    def test_inbound_adapters(self):
        # 1. Generic payload
        gen_payload = {
            "id": "gen_101",
            "message": "Как устроиться на работу инкассатором?",
            "user_id": "player_88",
            "callback_url": "https://example.com/reply",
            "attachments_count": 0,
        }
        adapted_gen = self.manager.adapt_inbound_ticket("generic", gen_payload)
        self.assertEqual(adapted_gen["ticket_id"], "gen_101")
        self.assertEqual(adapted_gen["messages"][0]["text"], "Как устроиться на работу инкассатором?")
        self.assertEqual(adapted_gen["callback_url"], "https://example.com/reply")
        self.assertEqual(adapted_gen["images_count"], 0)

        # 2. Telegram update
        tg_update = {
            "update_id": 9999,
            "message": {
                "message_id": 42,
                "from": {"id": 123456, "username": "ivan_grand", "first_name": "Иван"},
                "chat": {"id": 123456},
                "text": "Здравствуйте, подскажите команды сервера",
                "date": 1690000000,
            },
        }
        adapted_tg = self.manager.adapt_inbound_ticket("telegram", tg_update)
        self.assertIsNotNone(adapted_tg)
        self.assertEqual(adapted_tg["ticket_id"], "tg_123456_42")
        self.assertEqual(adapted_tg["source_crm"], "telegram")
        self.assertEqual(adapted_tg["messages"][0]["text"], "Здравствуйте, подскажите команды сервера")

        # 3. Zendesk payload
        zd_payload = {
            "ticket": {
                "id": 555,
                "subject": "Вопрос по игровому процессу",
                "description": "Где находится автосалон высокого класса?",
                "requester_id": 98765,
                "tags": ["vip", "mobile"],
            }
        }
        adapted_zd = self.manager.adapt_inbound_ticket("zendesk", zd_payload)
        self.assertEqual(adapted_zd["ticket_id"], "zd_555")
        self.assertEqual(adapted_zd["source_crm"], "zendesk")
        self.assertIn("автосалон", adapted_zd["messages"][0]["text"])

    def test_auto_reply_decision_matrix(self):
        async def run_async_test():
            # Case A: Safe question with high confidence -> Auto-reply
            safe_ticket = {
                "ticket_id": "safe_001",
                "source_crm": "generic_webhook",
                "messages": [{"role": "player", "text": "Как получить паспорт?"}],
            }
            safe_triage = {
                "category": "report.question",
                "priority": "p3",
                "needs_human": False,
                "confidence": 0.88,
                "draft_reply": {
                    "lang": "ru",
                    "text": "Здравствуйте! Для получения паспорта обратитесь в здание Правительства.",
                    "cited": ["3.1"],
                },
                "reasons": [],
            }

            res_safe = await self.manager.process_and_dispatch(safe_ticket, safe_triage)
            self.assertEqual(res_safe["action"], "AUTO_REPLIED")
            self.assertTrue(res_safe["auto_replied"])
            self.assertIsNotNone(res_safe["reply_sent"])

            # Case B: Sensitive complaint requiring human review -> Escalated
            human_ticket = {
                "ticket_id": "human_002",
                "source_crm": "generic_webhook",
                "messages": [{"role": "player", "text": "Админ дал бан ни за что! Доказательства есть."}],
            }
            human_triage = {
                "category": "complaint.admin",
                "priority": "p1",
                "needs_human": True,
                "confidence": 0.92,
                "draft_reply": {
                    "lang": "ru",
                    "text": "Здравствуйте! Ваша жалоба на администратора передана руководству сервера.",
                    "cited": ["1.1"],
                },
                "reasons": ["Жалобы на администрацию требуют ручной проверки"],
            }

            res_human = await self.manager.process_and_dispatch(human_ticket, human_triage)
            self.assertEqual(res_human["action"], "ESCALATED_TO_OPERATOR")
            self.assertFalse(res_human["auto_replied"])
            self.assertIsNone(res_human["reply_sent"])

        asyncio.run(run_async_test())

    def test_b2b_metrics_and_audit(self):
        metrics = self.manager.get_audit_metrics()
        self.assertIn("total_tickets", metrics)
        self.assertIn("auto_replied", metrics)
        self.assertIn("escalated_to_operator", metrics)
        self.assertIn("deflection_rate_pct", metrics)
        self.assertIn("operator_hours_saved", metrics)
        self.assertGreaterEqual(metrics["total_tickets"], 0)


def test_fastapi_endpoints():
    try:
        from fastapi.testclient import TestClient
        from app import app
        client = TestClient(app)

        # 1. Health
        h = client.get("/health")
        assert h.status_code == 200, f"Health check failed: {h.text}"

        # 2. Universal CRM Webhook
        resp = client.post(
            "/webhook/crm/ticket",
            json={
                "ticket_id": "e2e_crm_999",
                "text": "Подскажите пожалуйста команды анимаций",
                "lang": "ru",
            },
        )
        assert resp.status_code == 200, f"Webhook ticket failed: {resp.text}"
        data = resp.json()
        assert "action" in data
        assert "triage" in data

        # 3. Telegram Webhook
        resp_tg = client.post(
            "/webhook/telegram",
            json={
                "update_id": 1002,
                "message": {
                    "message_id": 101,
                    "from": {"id": 77777, "first_name": "Anna"},
                    "chat": {"id": 77777},
                    "text": "Как купить дом в игре?",
                },
            },
        )
        assert resp_tg.status_code == 200, f"Telegram webhook failed: {resp_tg.text}"

        # 4. Metrics
        resp_m = client.get("/crm/metrics")
        assert resp_m.status_code == 200
        assert "deflection_rate_pct" in resp_m.json()

        # 5. Config
        resp_c = client.get("/crm/config")
        assert resp_c.status_code == 200
        assert "auto_reply_enabled" in resp_c.json()

        print("✅ FastAPI B2B endpoints verified successfully!")
    except ImportError as e:
        print(f"Skipping TestClient test (httpx/testclient optional): {e}")


if __name__ == "__main__":
    print("🚀 Running Via Automation B2B CRM & Auto-Reply test suite...")
    suite = unittest.TestLoader().loadTestsFromTestCase(TestCRMConnectors)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if not result.wasSuccessful():
        sys.exit(1)

    print("\n🌐 Running FastAPI Webhook verification...")
    test_fastapi_endpoints()
    print("\n✨ ALL B2B CRM TESTS PASSED!")
