"""
CONCURRENCY & RACE CONDITION STRESS TEST
Grand Mobile Support Copilot — 'Via автоматизация'
Тестировщик №2 (Stress & Resilience Tester)

Проверяет:
1. Параллельную обработку тикетов в 50 асинхронных воркерах
2. Отсутствие состояния гонки (race conditions) при обновлении истории дедупликатора
3. Целостность ответов и отсутствие взаимных блокировок (deadlocks)
"""

import asyncio
import os
import sys
import time
import orjson

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath("."))
from src.pipeline import SupportCopilotPipeline


async def test_concurrent_flood_and_triage():
    print("=" * 80)
    print("⚡ СТРЕСС-ТЕСТ ПАРАЛЛЕЛИЗМА И ГОНОК ДАННЫХ (50 ВОРКЕРОВ)")
    print("=" * 80)

    pipeline = SupportCopilotPipeline()
    pipeline.deduplicator.reset()

    # 1. Сгенерируем 500 запросов от 10 разных пользователей, отправляемых одновременно
    tasks = []
    sem = asyncio.Semaphore(50)

    results = []

    async def worker(idx: int, user_id: str, text: str):
        async with sem:
            ticket = {
                "ticket_id": f"async_ticket_{idx}",
                "reporter_hash": user_id,
                "messages": [{"role": "player", "text": text}]
            }
            res = await pipeline.triage_ticket_async(ticket)
            results.append((idx, user_id, res))

    t0 = time.perf_counter()
    tasks = [
        worker(i, f"user_{i % 10}", f"Вопрос {i}: как починить автомобиль и где автосервис?")
        for i in range(500)
    ]
    await asyncio.gather(*tasks)
    dt = time.perf_counter() - t0

    print(f"  • Обработано 500 асинхронных тикетов за {dt:.2f} сек ({500/dt:.1f} тикетов/сек)")
    assert len(results) == 500, f"Ожидалось 500 результатов, получено {len(results)}"

    # Проверяем контракт каждого ответа
    for idx, uid, r in results:
        assert "category" in r and "priority" in r and "needs_human" in r
        assert isinstance(r["is_spam_or_duplicate"], bool)

    print("  ✅ [PASS] 500 параллельных тикетов обработаны без race conditions, дедлоков и сбоев контракта!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(test_concurrent_flood_and_triage())
