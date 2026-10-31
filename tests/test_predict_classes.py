import os
import sys
import time

sys.path.insert(0, os.path.abspath("."))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.classifier import predict_classes


def test_inference_and_latency():
    print("=" * 60)
    print("🧪 TESTING predict_classes(text, kind, images_count)")
    print("=" * 60)

    # Warmup
    w = predict_classes("меня дмят у банка", kind="complaint", images_count=1)
    print("Warmup test:", w)
    assert "category" in w and "priority" in w and "confidence" in w

    test_samples = [
        # Explicit anchors
        ("игрок летает на машине и стреляет сквозь стены читер", "complaint", 1),
        ("оскорбил мать в чате матом", "complaint", 1),
        ("оплатил донат 500 гк чек прикрепил но деньги не пришли", "report", 1),
        ("помогите застрял в текстурах вытащите пожалуйста", "report", 0),
        ("взял деньги за машину и оффнулся обманул скам", "complaint", 1),
        ("где устроиться на работу механика в игре", "report", 0),
        ("продаю вирты за реальные деньги в телеграм", "complaint", 1),
        ("администратор выдал бан ни за что жалоба на админа", "complaint", 1),
        # Pure ML CatBoost inference (no keywords from anchor lists)
        ("подозрительное поведение гражданина в форме ночью", "complaint", 1),
        ("человек ведет себя странно на призыве", "complaint", 0),
    ]

    latencies = []
    for text, kind, img_cnt in test_samples:
        t0 = time.perf_counter()
        res = predict_classes(text, kind=kind, images_count=img_cnt)
        dt = (time.perf_counter() - t0) * 1000.0
        latencies.append(dt)
        print(
            f"[{kind.upper():9s}] {text[:38]:38s} -> {res['category']:18s} | {res['priority']:3s} | Conf: {res['confidence']:.2f} ({dt:.2f} ms)"
        )

    avg_lat = sum(latencies) / len(latencies)
    max_lat = max(latencies)
    print("-" * 60)
    print(
        f"Latency benchmark: avg = {avg_lat:.2f} ms, max = {max_lat:.2f} ms (Target: < 20 ms)"
    )
    print("=" * 60)

    assert avg_lat < 20.0, f"Average latency {avg_lat:.2f} ms exceeds 20 ms target!"
    print("✅ All assertions passed successfully!")


if __name__ == "__main__":
    test_inference_and_latency()
