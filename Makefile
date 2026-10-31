IN ?= tickets_valid.jsonl
OUT ?= pred.jsonl

.PHONY: all build predict run benchmark docker-build docker-up docker-down clean help

all: predict

help:
	@echo "Grand Mobile Support Copilot — 100% Native C++20 HFT Server"
	@echo "  make build                                 : Build C++ binaries (Release -O3 -flto)"
	@echo "  make predict IN=<in.jsonl> OUT=<out.jsonl> : Run high-speed C++ batch prediction"
	@echo "  make run                                   : Start C++ Crow REST API server (port 8000)"
	@echo "  make benchmark                             : Run native C++ benchmark tool"
	@echo "  make docker-build                          : Build multi-stage C++ Docker image"
	@echo "  make docker-up                             : Start services via docker-compose"
	@echo "  make docker-down                           : Stop containers"
	@echo "  make clean                                 : Clean build artifacts"

build:
	cmake -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j

predict:
	./build/benchmark_tool --predict $(IN) $(OUT)

run:
	./build/grand_mobile_server rules.json models/classifier.onnx

benchmark:
	./build/benchmark_tool tickets_valid.jsonl

docker-build:
	docker compose build

docker-up:
	docker compose up -d

docker-down:
	docker compose down

clean:
	rm -rf build
