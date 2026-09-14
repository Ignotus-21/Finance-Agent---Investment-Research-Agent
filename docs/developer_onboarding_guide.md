# Developer Onboarding & Setup Guide
## Autonomous Investment Research Intelligence Agent (IRA)

---

### Document Control
- **Document Version:** 1.0.0
- **Target Audience:** Quantitative Software Engineers, AI Engineers, Financial Engineers

---

## 1. Prerequisites & Toolchains

Before contributing to the IRA project, verify your workstation has the following installed:
- **Python:** Version 3.11 or 3.12 (`python3 --version`)
- **Git:** Version 2.40+ (`git --version`)
- **Docker:** Docker Desktop or Colima for container packaging (`docker --version`)
- **Google Cloud SDK:** `gcloud` CLI authenticated with GCP permissions (`gcloud auth login`)
- **Make:** Standard build utility (`make --version`)

---

## 2. Local Sandbox Setup

### Step 2.1: Clone the Repository
```bash
git clone https://github.com/Ignotus-21/Finance-Agent---Investment-Research-Agent.git
cd Finance-Agent---Investment-Research-Agent
```

### Step 2.2: Create and Activate Virtual Environment
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Step 2.3: Install Dependencies (Application & Development)
```bash
# Install package in editable mode with development tooling
pip install --upgrade pip
pip install -e .[dev]
```

### Step 2.4: Configure Environment Variables
Copy the template configuration file:
```bash
cp .env.example .env
```
Ensure `.env` contains:
```ini
ENVIRONMENT=development
DEBUG=True
GCP_PROJECT_ID=ira-capstone-finance-prod
GCP_REGION=us-central1
COORDINATOR_MODEL=gemini-2.5-pro
EXTRACTION_MODEL=gemini-2.5-flash
THINKING_BUDGET=2048
SEC_EDGAR_USER_AGENT="SampleInstitutionalResearch AdminContact@samplecompany.com"
SEC_RATE_LIMIT_PER_SEC=8.0
CONTEXT_CACHE_TTL_MINUTES=60
MAX_BRIEF_COST_USD=0.25
```

---

## 3. Developer Quality Tooling & Commands

All development workflows are standardized via the project `Makefile`:

```mermaid
graph LR
    Code[Write Code] --> Lint[make lint<br/>Ruff & MyPy]
    Lint --> Test[make test<br/>Pytest >= 80% Cov]
    Test --> Eval[make eval<br/>Golden Regression Gate]
    Eval --> Commit[Git Conventional Commit]
```

### 3.1 Automated Testing & Code Coverage
Run the full unit, integration, and chaos test suites:
```bash
make test
# Direct invocation with coverage threshold assertion:
pytest --cov=src --cov-fail-under=80 --cov-report=term-missing -v
```

### 3.2 Evaluation Benchmark Regression Gate
Execute the automated evaluation suite against the 52 scenarios in the Golden Dataset:
```bash
make eval
# Direct invocation:
python -m eval.regression_gate
```

### 3.3 Linting & Static Type Checking
Assert code formatting and type safety:
```bash
make lint
# Direct invocation:
ruff check src/ tests/
mypy src/ --ignore-missing-imports
```

### 3.4 Launch Local Development Server
Start the FastAPI server locally on port 8080 with live reload:
```bash
make run
# Server will be accessible at:
# API Docs: http://localhost:8080/docs
# ReDoc: http://localhost:8080/redoc
```

---

## 4. Git Multi-Branch Workflow & Contribution Standards

The IRA repository enforces **Trunk-Based / GitFlow development** with strict Conventional Commits:

1. **Branch Naming:**
   - Feature branches: `feature/<phase>-<description>` (e.g. `feature/phase3-sec-edgar-mcp`)
   - Bug fixes: `fix/<issue-description>`
   - Documentation: `docs/<description>`

2. **Conventional Commit Format:**
   ```
   <type>(<scope>): <subject>

   [optional body]
   ```
   *Examples:*
   - `feat(sec-agent): implement XBRL line-item extraction with citation provenance`
   - `fix(guardrail): refine stock speculation regex to capture comma-separated shares`
   - `test(chaos): add circuit breaker 5-failure trip test`
   - `docs(adr): document ADR-003 context caching decision`

3. **Pull Request Quality Gates:**
   Every PR must satisfy:
   - Zero linter or type-check warnings (`ruff`, `mypy`).
   - $\ge 80\%$ test coverage on new code.
   - All Golden Dataset quality thresholds satisfied (Faithfulness = 1.0, Relevance $\ge 0.90$, Citation Precision = 1.0).
   - Completed checklist against the 32 CPSE-to-FDE competencies in `.github/pull_request_template.md`.
