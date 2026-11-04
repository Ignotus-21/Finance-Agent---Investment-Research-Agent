.PHONY: help install install-ui hooks hooks-run lint typecheck test test-unit test-integration test-chaos eval eval-vertex run run-local ui adk-run adk-web docker-build docker-run clean infra-validate infra-plan infra-apply infra-output infra-pause infra-resume infra-destroy infra-import model-armor-create model-armor-delete

# Resolve the project virtualenv interpreter when present so every target works
# whether or not `.venv` has been activated in the current shell.
VENV ?= .venv
PY   := $(if $(wildcard $(VENV)/bin/python),$(VENV)/bin/python,python3)

help:
	@echo "Available commands:"
	@echo "  make install      Install application + dev dependencies and activate Git pre-commit hooks"
	@echo "  make install-ui   Install the Streamlit console extra (.[dev,ui])"
	@echo "  make hooks        Install the Git pre-commit hooks only"
	@echo "  make hooks-run    Run every pre-commit hook against all files (CI parity check)"
	@echo "  make lint         Run Ruff linter and MyPy static type checks"
	@echo "  make test         Execute unit, integration, and chaos test suites (assert >=80% coverage)"
	@echo "  make eval         Execute the 52-scenario Golden Evaluation regression gate"
	@echo "  make eval-vertex  Score with Vertex AI Gen AI Evaluation (billable, opt-in)"
	@echo "  make run          Launch local FastAPI server on http://localhost:8080"
	@echo "  make ui           Launch the Streamlit console on http://localhost:8502"
	@echo "  make adk-run      Run the ADK agent in an interactive terminal REPL"
	@echo "  make adk-web      Launch the ADK Web UI playground on http://localhost:8501"
	@echo "  make docker-build Build the production container image"
	@echo "  make docker-run   Run the containerized service locally"
	@echo "  make clean        Remove cache and build artifacts"

install:
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev]"
	$(MAKE) hooks

install-ui:
	$(PY) -m pip install -e ".[dev,ui]"

hooks:
	$(PY) -m pre_commit install

hooks-run:
	$(PY) -m pre_commit run --all-files

lint:
	$(PY) -m ruff check src/ tests/ scripts/ eval/ ui/
	$(PY) -m mypy src/

typecheck:
	$(PY) -m mypy src/

test-unit:
	$(PY) -m pytest tests/unit/ -v

test-integration:
	$(PY) -m pytest tests/integration/ -v

test-chaos:
	$(PY) -m pytest tests/chaos/ -v

test:
	$(PY) -m pytest --cov=src --cov-fail-under=80 --cov-report=term-missing

eval:
	$(PY) -m eval.regression_gate

eval-vertex:
	$(PY) -m eval.evaluate_golden_dataset --backend=vertex --project=$${GCP_PROJECT_ID}

run:
	$(PY) -m uvicorn src.api.app:app --host 0.0.0.0 --port 8080 --reload

run-local: run

# URL defaults to the local server started by `make run`. Target a deployed
# revision with:
#   make ui URL=https://<service>.run.app SA=<caller-sa> AUDIENCE=<audience>
URL      ?= http://localhost:8080
SA       ?=
AUDIENCE ?=
ui:
	IRA_SERVICE_URL="$(URL)" \
	IRA_IMPERSONATE_SA="$(SA)" \
	IRA_AUDIENCE="$(AUDIENCE)" \
	$(PY) -m streamlit run ui/streamlit_app.py --server.port 8502

adk-run:
	$(PY) -m google.adk.cli run src/agents

ADK_PORT ?= 8501
adk-web:
	$(PY) -m google.adk.cli web src --port $(ADK_PORT)

docker-build:
	docker build -t ira-service:latest .

docker-run:
	docker run -p 8080:8080 --env-file .env ira-service:latest

clean:
	rm -rf __pycache__ .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage dist build *.egg-info

# --- Infrastructure lifecycle (Terraform via scripts/infra.sh) -------------
# Requires terraform/backend.hcl and terraform/terraform.tfvars.
infra-validate:
	scripts/infra.sh validate

infra-plan:
	scripts/infra.sh plan

infra-apply:
	scripts/infra.sh apply

infra-output:
	scripts/infra.sh output

# Cost pause: scale the research service to zero warm instances.
infra-pause:
	scripts/infra.sh pause

infra-resume:
	scripts/infra.sh resume

# Kill switch: destroy every Terraform-managed resource.
infra-destroy:
	scripts/infra.sh destroy

# One-time adoption of pre-existing resources into Terraform state.
infra-import:
	PROJECT_ID=$(PROJECT_ID) REGION=$(REGION) ENVIRONMENT=$(ENVIRONMENT) scripts/infra_import_existing.sh

# Model Armor template (not managed by the pinned Terraform provider). Run
# model-armor-create before infra-apply; model-armor-delete after infra-destroy.
model-armor-create:
	scripts/model_armor_template.sh create $(PROJECT_ID) $(REGION)

model-armor-delete:
	scripts/model_armor_template.sh delete $(PROJECT_ID) $(REGION)
