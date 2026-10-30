IN ?= tickets_valid.jsonl
OUT ?= pred.jsonl

.PHONY: all train predict run ui cluster clean help

all: predict

help:
	@echo "Grand Mobile Support Copilot — Command List:"
	@echo "  make predict IN=<in.jsonl> OUT=<out.jsonl> : Run batch inference"
	@echo "  make run                                   : Start FastAPI server (port 8000)"
	@echo "  make ui                                    : Start Streamlit Admin UI"
	@echo "  make train                                 : Train fast ML classifier"
	@echo "  make cluster                               : Run template clustering (Bonus 2)"
	@echo "  make clean                                 : Remove cache and temporary files"

predict:
	python predict.py --in $(IN) --out $(OUT)

run:
	python -m uvicorn app:app --host 0.0.0.0 --port 8000

ui:
	python -m streamlit run admin_ui.py

train:
	python train_classifier.py

cluster:
	python src/template_clustering.py

clean:
	rm -rf __pycache__ src/__pycache__ .pytest_cache
