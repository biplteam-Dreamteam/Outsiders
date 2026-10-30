#!/usr/bin/env python3
"""
Grand Mobile Support Copilot - Pipeline Calibration & Stress Testing
Decentrathon 6.0 - Case 03

Validates 50 approved tickets from tickets_train.jsonl.gz against ground truth admin violations.
Simulates 'ELECTRIC SHOCK / FATAL ERROR' on any mismatch until 100% precision is achieved.
"""

import gzip
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.abspath("."))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.pipeline import SupportCopilotPipeline


def parse_ground_truth_rule(ticket: dict) -> str | None:
    v = str(ticket.get("violation", ""))
    nums = re.findall(r"\b\d+\.\d+\b", v)
    if nums:
        return nums[0]

    v_low = v.lower()
    if "deathmatch" in v_low or "dm" in v_low or "дм" in v_low:
        return "5.3"
    if "driveby" in v_low or "db" in v_low or "дб" in v_low:
        return "5.3"
    if "ск" in v_low or "sk" in v_low or "спавн" in v_low:
        return "5.4"
    if "уход от рп" in v_low or "урп" in v_low or "нрп" in v_low:
        return "5.3"
    if "чит" in v_low or "софт" in v_low:
        return "5.2"
    if "скам" in v_low or "обман" in v_low:
        return "4.1"

    return None


def load_calibration_dataset(file_path: str, count: int = 50) -> list[dict]:
    tickets = []
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Training dataset not found: {file_path}")

    with gzip.open(file_path, "rt", encoding="utf-8") as f:
        for line in f:
            t = json.loads(line)
            if t.get("verdict") == "approved":
                gt = parse_ground_truth_rule(t)
                if gt:
                    t["_gt_rule"] = gt
                    tickets.append(t)
                    if len(tickets) >= count:
                        break
    return tickets


def run_calibration():
    print("=" * 72)
    print("⚡ GRAND MOBILE COPILOT: STRICT PIPELINE CALIBRATION (50 TICKETS) ⚡")
    print("=" * 72)
    print("Testing mode: STRICT EVALUATION. Zero tolerance for rule hallucinations.")
    print("Electric Shock Simulation: ACTIVE.\n")

    train_path = "tickets_train.jsonl.gz"
    dataset = load_calibration_dataset(train_path, count=50)
    print(f"Loaded {len(dataset)} approved tickets with verified admin violations.\n")

    pipeline = SupportCopilotPipeline(rules_path="rules.json")

    passed = 0
    failed = 0
    t0 = time.time()

    for idx, ticket in enumerate(dataset, 1):
        t_id = ticket["ticket_id"]
        gt_rule = ticket["_gt_rule"]
        admin_violation = ticket.get("violation", "")

        # Process through pipeline
        res = pipeline.triage_ticket_sync(ticket)
        cited = res.get("draft_reply", {}).get("cited", [])

        # Check match
        if gt_rule in cited:
            passed += 1
            print(
                f"[{idx:02d}/50] PASS: Ticket #{t_id} | Violation: '{admin_violation}' -> Cited: {cited} ✅"
            )
        else:
            failed += 1
            print(
                f"\n[{idx:02d}/50] ⚡⚡⚡ УДАР ТОКОМ / ELECTRIC SHOCK! FATAL ERROR! ⚡⚡⚡"
            )
            print(f"Ticket ID:        {t_id}")
            print(f"Admin Violation:  '{admin_violation}'")
            print(f"Ground Truth Ref: {gt_rule}")
            print(f"Pipeline Cited:   {cited}")
            print(f"Category:         {res.get('category')}")
            print("=" * 72)

    total_time = time.time() - t0
    precision = (passed / len(dataset)) * 100.0

    print("\n" + "=" * 72)
    print("📊 CALIBRATION SUMMARY RESULTS:")
    print(f"   Total Tickets Tested: {len(dataset)}")
    print(f"   Matched / Verified:   {passed}")
    print(f"   Failed / Shocks:      {failed}")
    print(f"   Precision Rate:       {precision:.2f}%")
    print(
        f"   Total Time:           {total_time:.2f}s ({total_time / len(dataset) * 1000:.1f} ms/ticket)"
    )
    print("=" * 72)

    if precision == 100.0 and failed == 0:
        print("\n🏆 SUCCESS: 100% PRECISION ACHIEVED!")
        print("⚡ ZERO ELECTRIC SHOCKS RECEIVED. All 50 tickets perfectly calibrated.")
        print("✅ Pipeline conforms 100% to Grand Mobile referee standards.\n")
        return 0
    else:
        print(
            f"\n❌ CALIBRATION FAILED: Precision {precision:.1f}% < 100%. Electric shocks delivered: {failed}"
        )
        return 1


if __name__ == "__main__":
    exit_code = run_calibration()
    sys.exit(exit_code)
