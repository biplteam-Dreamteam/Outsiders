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

from src.classifier import TicketClassifier
from src.pipeline import SupportCopilotPipeline
from src.rag_engine import RAGEngine, RuleValidator
from src.rule_manager import (
    DEFAULT_RULES_PATH,
    extract_categories_from_rules,
    get_active_rules_path,
    parse_rules_content,
    save_active_rules,
)


class TestUniversalCopilotWithoutGameWeights(unittest.TestCase):
    def test_no_game_weights_in_active_models(self):
        """Проверяет, что старые игровые веса убраны из активной папки models/."""
        models_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")
        root_cbm = [f for f in os.listdir(models_dir) if f.endswith(".cbm")]
        root_joblib = [f for f in os.listdir(models_dir) if f.endswith(".joblib")]
        self.assertEqual(len(root_cbm), 0, f"Found active cbm models in root: {root_cbm}")
        self.assertEqual(len(root_joblib), 0, f"Found active joblib models in root: {root_joblib}")

    def test_dynamic_classifier_works_autonomously(self):
        """Проверяет, что классификатор работает сам без весов на основе активных правил."""
        clf = TicketClassifier()
        self.assertTrue(clf.is_trained(), "Classifier should be trained/indexed from active rules")
        self.assertGreater(len(clf.categories), 0, "Classifier must have dynamic categories")

        # Test billing question
        res_billing = clf.predict_classes("Здравствуйте, как оформить возврат средств за подписку?")
        self.assertIn("billing", res_billing["category"])
        self.assertGreater(res_billing["confidence"], 0.60)

        # Test security question
        res_sec = clf.predict_classes("Мой аккаунт взломали, украли доступ, срочно заблокируйте!")
        self.assertIn("account", res_sec["category"])
        self.assertIn(res_sec["priority"], ["p0", "p1"])

        # Test SLA question
        res_sla = clf.predict_classes("Подскажите ваш график работы и сколько ждать ответа?")
        self.assertIn("support", res_sla["category"])
        self.assertEqual(res_sla["priority"], "p3")

    def test_upload_custom_rules_markdown(self):
        """Проверяет загрузку и парсинг правил из произвольного текста Markdown."""
        markdown_text = """
# 1. Доставка и логистика
1.1 Сроки курьерской доставки составляют от 1 до 3 рабочих дней.
1.2 Бесплатная доставка предоставляется при сумме заказа от 5000 рублей.

# 2. Возврат и обмен товара
2.1 Покупатель вправе вернуть товар надлежащего качества в течение 14 дней.
2.2 При обнаружении производственного брака возврат средств осуществляется в течение 24 часов.
"""
        parsed = parse_rules_content(markdown_text)
        self.assertEqual(len(parsed["rules"]), 2)
        total_points = sum(len(sec["points"]) for sec in parsed["rules"])
        self.assertEqual(total_points, 4)

        # Проверяем автоматическое извлечение категорий
        cats = extract_categories_from_rules(parsed)
        self.assertTrue(any("delivery" in c or "order" in c for c in cats))
        self.assertTrue(any("quality" in c or "product" in c or "billing" in c for c in cats))

    def test_dynamic_reindexing_on_custom_rules(self):
        """
        Проверяет полный цикл обновления базы знаний:
        Загрузка новых правил E-Commerce -> переиндексация RAG и классификатора ->
        проверка правильного ответа и цитирования новых правил!
        """
        custom_ecommerce_rules = {
            "name": "E-Commerce Store Rules",
            "version": "1.0.0",
            "rules": [
                {
                    "id": 1,
                    "category": "Служба доставки",
                    "points": [
                        {
                            "ref": "10.1",
                            "title": "Сроки доставки курьером",
                            "category": "ecommerce.delivery",
                            "keywords": ["доставка", "курьер", "где заказ", "когда приедет", "трек", "посылка"],
                            "text": "Курьерская доставка осуществляется ежедневно с 09:00 до 21:00. Номер отслеживания доступен в личном кабинете.",
                        }
                    ],
                },
                {
                    "id": 2,
                    "category": "Гарантия и возврат",
                    "points": [
                        {
                            "ref": "20.1",
                            "title": "Возврат бракованного товара",
                            "category": "ecommerce.returns",
                            "keywords": ["брак", "сломан", "не работает товар", "возврат товара", "дефект"],
                            "text": "В случае обнаружения брака покупатель может вернуть товар и получить 100% возврат средств или замену на новый экземпляр.",
                        }
                    ],
                },
            ],
        }

        # Инициализируем RAG и Classifier
        rag = RAGEngine()
        clf = TicketClassifier()

        # Применяем новые правила
        rag.reload_rules(custom_ecommerce_rules)
        clf.reindex_from_rules(custom_ecommerce_rules)

        # 1. Проверяем валидатор
        self.assertTrue(rag.validator.is_valid("10.1"))
        self.assertTrue(rag.validator.is_valid("20.1"))
        self.assertFalse(rag.validator.is_valid("99.99"))

        # 2. Проверяем RAG поиск по новым правилам
        retrieved = rag.retrieve("Где мой заказ, когда приедет курьер с посылкой?", top_k=2)
        self.assertGreater(len(retrieved), 0)
        self.assertEqual(retrieved[0]["ref"], "10.1")

        # 3. Проверяем классификатор по новым категориям
        pred = clf.predict_classes("Товар пришел сломанным, есть заводской дефект, как вернуть?")
        self.assertEqual(pred["category"], "ecommerce.returns")

    def test_pipeline_async_triage_with_dynamic_rules(self):
        """Проверяет сквозной пайплайн SupportCopilotPipeline на произвольном корпоративном тикете."""
        async def run_pipeline():
            pipeline = SupportCopilotPipeline()
            ticket = {
                "ticket_id": "corp_ticket_1001",
                "kind": "report",
                "lang": "ru",
                "messages": [
                    {
                        "role": "player",
                        "text": "Здравствуйте, подскажите регламентные сроки ответа вашей поддержки?",
                    }
                ],
            }

            result = await pipeline.triage_ticket_async(ticket)
            self.assertIn("category", result)
            self.assertIn("priority", result)
            self.assertIn("draft_reply", result)
            self.assertTrue(len(result["draft_reply"]["text"]) > 0)
            # Убеждаемся, что в ответе нет упоминаний Grand Mobile
            self.assertNotIn("Grand Mobile", result["draft_reply"]["text"])

        asyncio.run(run_pipeline())


def test_fastapi_rules_endpoints():
    try:
        from fastapi.testclient import TestClient
        from app import app
        client = TestClient(app)

        # 1. Get active rules
        r = client.get("/rules/active")
        assert r.status_code == 200
        data = r.json()
        assert "rules_count" in data
        assert "categories" in data
        assert data["rules_count"] > 0

        # 2. Upload custom rules via JSON
        new_policy = {
            "name": "Fintech Support Policy",
            "version": "3.0.0",
            "rules": [
                {
                    "category": "Криптовалютные переводы",
                    "points": [
                        {
                            "ref": "7.1",
                            "title": "Подтверждение блокчейн-транзакций",
                            "category": "crypto.transfer",
                            "keywords": ["крипта", "биткоин", "usdt", "хеш", "блокчейн"],
                            "text": "Переводы зачисляются после 3 подтверждений сети блокчейн.",
                        }
                    ],
                }
            ],
        }
        resp_up = client.post("/rules/upload", json=new_policy)
        assert resp_up.status_code == 200
        up_data = resp_up.json()
        assert up_data["status"] == "success"
        assert "crypto.transfer" in up_data["categories"]

        # 3. Test triage of crypto ticket under the newly uploaded policy
        triage_resp = client.post(
            "/webhook/crm/ticket",
            json={
                "ticket_id": "crypto_001",
                "text": "Отправил перевод в USDT, сколько подтверждений сети требуется?",
                "lang": "ru",
            },
        )
        assert triage_resp.status_code == 200
        t_data = triage_resp.json()
        assert t_data["triage"]["category"] == "crypto.transfer"
        assert "7.1" in t_data["triage"]["draft_reply"]["cited"]

        # 4. Reset rules back to default
        resp_reset = client.post("/rules/reset")
        assert resp_reset.status_code == 200
        assert resp_reset.json()["status"] == "success"

        print("✅ FastAPI /rules/upload, /rules/active, /rules/reset verified successfully!")
    except ImportError as e:
        print(f"Skipping TestClient test: {e}")


if __name__ == "__main__":
    print("🚀 Running Universal Copilot & Dynamic Rules test suite...")
    suite = unittest.TestLoader().loadTestsFromTestCase(TestUniversalCopilotWithoutGameWeights)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if not result.wasSuccessful():
        sys.exit(1)

    print("\n🌐 Running FastAPI Rules API verification...")
    test_fastapi_rules_endpoints()
    print("\n✨ ALL TESTS PASSED: System operates 100% autonomously without game weights!")
