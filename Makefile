.PHONY: help install install-ui hooks hooks-run test lint eval eval-vertex run ui adk-run adk-web docker-build docker-run clean

help:
	@echo "Available commands:"
	@echo "  make install      Install application dependencies and activate Git pre-commit hooks"
	@echo "  make hooks        Install the Git pre-commit hooks only"
	@echo "  make hooks-run    Run every pre-commit hook against all files (CI parity check)"
	@echo "  make test         Execute unit, integration, and chaos test suites (assert >=80% coverage)"
	@echo "  make eval         Execute Golden Evaluation Benchmark regression gate"
	@echo "  make eval-vertex  Score with Vertex AI Gen AI Evaluation (billable, opt-in)"
	@echo "  make lint         Run Ruff linter and static type checks"
	@echo "  make run          Launch local FastAPI server on port 8080"
	@echo "  make ui           Launch the Streamlit test console (needs make install-ui)"
	@echo "  make adk-run      Run ADK agent in interactive terminal REPL"
	@echo "  make adk-web      Launch ADK agent Web UI playground on port 8501"
	@echo "  make docker-build Build production container image"
	@echo "  make docker-run   Run containerized service locally"
	@echo "  make clean        Remove cache and build artifacts"

install:
	pip install -e .[dev]
	$(MAKE) hooks

# Separate from `install` so Streamlit stays out of the default developer
# environment and, more importantly, out of the container image.
install-ui:
	pip install -e ".[dev,ui]"

# Chained onto `install` so a fresh clone gets the hooks without a second,
# easily-forgotten step. Hooks that nobody installs never run.
hooks:
	pre-commit install

hooks-run:
	pre-commit run --all-files

test:
	pytest --cov=src --cov-fail-under=80 --cov-report=term-missing -v

eval:
	python -m eval.regression_gate

eval-vertex:
	@# Billable and non-deterministic, which is why it is a separate target and
	@# not part of `make eval` or CI. Needs: pip install -e ".[dev,eval]"
	python -m eval.evaluate_golden_dataset --backend=vertex --project=$${GCP_PROJECT_ID}

lint:
	@# Same paths CI checks. When these drifted apart, a lint error in scripts/
	@# passed locally and failed the workflow.
	ruff check src/ tests/ scripts/ eval/ ui/
	mypy src/ --ignore-missing-imports

run:
	uvicorn src.api.app:app --host 0.0.0.0 --port 8080 --reload

# URL defaults to the local server started by `make run`. Point it at a
# deployed revision with: make ui URL=https://ira-service-production-....run.app
URL ?= http://localhost:8080
ui:
	@# SA and AUDIENCE prefill the sidebar. Against a deployed service both are
	@# required: a user account cannot mint an ID token for a custom audience,
	@# and a token whose aud is the run.app URL passes Cloud Run IAM and is then
	@# rejected by the application. Neither is needed against localhost.
	@#   make ui URL=https://... SA=ira-caller-test-sa@proj.iam.gserviceaccount.com AUDIENCE=ira-service-test
	IRA_SERVICE_URL="$(URL)" \
	IRA_IMPERSONATE_SA="$(SA)" \
	IRA_AUDIENCE="$(AUDIENCE)" \
	streamlit run ui/streamlit_app.py --server.port 8502

adk-run:
	adk run src/agents

adk-web:
	adk web src/agents --port 8501

docker-build:
	docker build -t ira-service:latest .

docker-run:
	docker run -p 8080:8080 --env-file .env ira-service:latest

clean:
	rm -rf .pytest_cache .coverage htmlcov .ruff_cache .mypy_cache build dist *.egg-info
