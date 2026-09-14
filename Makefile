.PHONY: help install test lint eval run docker-build docker-run clean

help:
	@echo "Available commands:"
	@echo "  make install      Install application dependencies"
	@echo "  make test         Execute unit, integration, and chaos test suites (assert >=80% coverage)"
	@echo "  make eval         Execute Golden Evaluation Benchmark regression gate"
	@echo "  make lint         Run Ruff linter and static type checks"
	@echo "  make run          Launch local FastAPI server on port 8080"
	@echo "  make docker-build Build production container image"
	@echo "  make docker-run   Run containerized service locally"
	@echo "  make clean        Remove cache and build artifacts"

install:
	pip install -e .[dev]

test:
	pytest --cov=src --cov-fail-under=80 --cov-report=term-missing -v

eval:
	python -m eval.regression_gate

lint:
	ruff check src/ tests/
	mypy src/ --ignore-missing-imports

run:
	uvicorn src.api.app:app --host 0.0.0.0 --port 8080 --reload

docker-build:
	docker build -t ira-multiagent-service:latest .

docker-run:
	docker run -p 8080:8080 --env-file .env ira-multiagent-service:latest

clean:
	rm -rf .pytest_cache .coverage htmlcov .ruff_cache .mypy_cache build dist *.egg-info
