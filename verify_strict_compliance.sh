#!/bin/bash
set -e
python verify_strict_compliance.py "${1:-pred.jsonl}"

