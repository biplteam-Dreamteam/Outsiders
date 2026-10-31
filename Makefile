IN ?= tickets_valid.jsonl
OUT ?= pred.jsonl

.PHONY: all prepare train predict run ui cluster docker-build docker-up docker-down test torture verify calibrate lint format help

all: predict

help:
	@echo "Grand Mobile Support Copilot — Command List:"
	@echo "  make predict IN=<in.jsonl> OUT=<out.jsonl> : Run batch inference"
	@echo "  make verify OUT=<out.jsonl>                : Verify 100% compliance on predictions"
	@echo "  make torture                               : Run organizer 20-case torture test suite"
	@echo "  make run                                   : Start FastAPI server (port 8000)"
	@echo "  make ui                                    : Start Streamlit Admin UI (port 8501)"
	@echo "  make cluster                               : Run template clustering (Bonus 2)"
	@echo "  make test                                  : Run unit and contract test suite"
	@echo "  make docker-build                          : Build Docker images"
	@echo "  make docker-up                             : Start services in Docker containers"
	@echo "  make docker-down                           : Stop Docker containers"

predict:
	python src/predict.py --in $(IN) --out $(OUT)

verify:
	python verify_strict_compliance.py $(OUT)

torture:
	python test_organizer_torture.py

run:
	python -m uvicorn main:app --host 0.0.0.0 --port 8000

ui:
	python -m streamlit run admin_ui.py --server.port 8501 --server.address 0.0.0.0

prepare:
	python src/prepare_dataset.py

train:
	python src/train_classifier.py

cluster:
	python src/template_clustering.py

calibrate:
	python calibrate_pipeline.py

test:
	python tests/test_contract.py
	python tests/test_api.py
	python tests/test_predict_classes.py
	python tests/test_kazakh_reply.py
	python src/final_tests.py
	python calibrate_pipeline.py

stress:
	python src/final_tests.py

profile:
	python src/run_profiler.py

benchmark:
	python src/benchmark_2k.py 2000

load-test:
	python src/load_test.py --count 50000 --concurrency 50

docker-build:
	docker compose build

docker-up:
	docker compose up -d

docker-down:
	docker compose down

format:
	python -m ruff format .
	python -m ruff check --fix .
