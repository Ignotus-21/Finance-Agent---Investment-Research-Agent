"""
Application Configuration Module using Pydantic Settings.
Loads baseline defaults from configs/settings.yaml and overrides via
environment variables (or a local .env file).
"""

from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SAMPLE_SEC_USER_AGENT = "SampleInstitutionalResearch AdminContact@samplecompany.com"
SAMPLE_GCP_PROJECT_ID = "ira-capstone-finance-prod"

_SETTINGS_YAML_PATH = Path(__file__).resolve().parents[1] / "configs" / "settings.yaml"


def load_yaml_settings(path: Path = _SETTINGS_YAML_PATH) -> dict[str, Any]:
    """Load structured defaults from configs/settings.yaml if present."""
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


_YAML_DEFAULTS = load_yaml_settings()
_MODELS_CFG = _YAML_DEFAULTS.get("models", {})
_GENERATION_CFG = _MODELS_CFG.get("generation", {})
_SAFETY_CFG = _MODELS_CFG.get("safety", {})
_GUARDRAILS_CFG = _YAML_DEFAULTS.get("guardrails", {})
_RESILIENCE_CFG = _YAML_DEFAULTS.get("resilience", {})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application Metadata
    app_name: str = "Autonomous Investment Research Intelligence Agent (IRA)"
    environment: str = Field(default="development", description="development, staging, production")
    debug: bool = Field(default=False)
    api_port: int = Field(default=8080)

    # Google Cloud Platform Settings
    gcp_project_id: str = Field(default=SAMPLE_GCP_PROJECT_ID, description="GCP Project ID")
    gcp_region: str = Field(default="us-central1", description="Target GCP Region")

    # Model Tier, Generation & Safety Settings (defaults from configs/settings.yaml)
    coordinator_model: str = Field(
        default=_MODELS_CFG.get("coordinator_model", "gemini-2.5-pro"),
        description="Model for root planner & synthesis",
    )
    extraction_model: str = Field(
        default=_MODELS_CFG.get("extraction_model", "gemini-2.5-flash"),
        description="Model for high-throughput parsing",
    )
    temperature: float = Field(
        default=float(_GENERATION_CFG.get("temperature", 0.1)),
        description="Sampling temperature for all agents (low for deterministic financial output)",
    )
    top_p: float = Field(
        default=float(_GENERATION_CFG.get("top_p", 0.95)),
        description="Nucleus sampling probability mass",
    )
    max_output_tokens: int = Field(
        default=int(_GENERATION_CFG.get("max_output_tokens", 8192)),
        description="Maximum output tokens per model response",
    )
    coordinator_thinking_budget: int = Field(
        default=int(_GENERATION_CFG.get("coordinator_thinking_budget", 2048)),
        description="Gemini 2.5 Pro thinking token budget for the root coordinator",
    )
    safety_harm_block_threshold: str = Field(
        default=str(_SAFETY_CFG.get("harm_block_threshold", "BLOCK_MEDIUM_AND_ABOVE")),
        description="Gemini safety threshold applied to every harm category",
    )

    # Financial Ingestion & SEC Rate Limiting
    offline_mode: bool = Field(
        default=True,
        description="Serve SEC data from bundled fixtures when True; query live data.sec.gov when False.",
    )
    sec_edgar_user_agent: str = Field(
        default=SAMPLE_SEC_USER_AGENT,
        description="Compliant SEC.gov User-Agent header identifying organization and contact email.",
    )
    sec_rate_limit_per_sec: float = Field(
        default=float(_RESILIENCE_CFG.get("sec_rate_limit_per_sec", 8.0)),
        description="Max SEC requests/sec (SEC ceiling is 10)",
    )
    sec_http_timeout_seconds: float = Field(
        default=float(_RESILIENCE_CFG.get("sec_http_timeout_seconds", 20.0)),
        description="Per-request timeout for live SEC EDGAR calls",
    )
    sec_http_max_retries: int = Field(
        default=int(_RESILIENCE_CFG.get("sec_http_max_retries", 3)),
        description="Retry attempts for SEC 429/5xx responses",
    )
    subagent_timeout_seconds: float = Field(
        default=float(_RESILIENCE_CFG.get("subagent_timeout_seconds", 45.0)),
        description="Upper bound for each sub-agent task in the REST research pipeline",
    )

    # Context Caching & Budget Caps
    context_cache_ttl_minutes: int = Field(default=60, description="Gemini context cache TTL in minutes")
    max_brief_cost_usd: float = Field(default=0.25, description="Target max inference cost per research brief")

    # Security, Privacy & DLP
    auth_allowed_audiences: str = Field(
        default="",
        description="Comma-separated audiences accepted on incoming Google-signed OIDC ID tokens.",
    )
    enable_dlp_masking: bool = Field(default=True, description="Enable PII redaction on inbound prompts")
    dlp_backend: str = Field(
        default=str(_GUARDRAILS_CFG.get("dlp_backend", "regex")),
        description="PII redaction backend: 'regex' (in-process) or 'cloud_dlp' (Cloud DLP de-identification)",
    )
    enforce_guardrails: bool = Field(default=True, description="Enforce pre-execution prompt injection filter")
    max_prompt_chars: int = Field(
        default=int(_GUARDRAILS_CFG.get("max_prompt_chars", 8000)),
        description="Maximum accepted prompt length in characters",
    )
    enable_live_news_grounding: bool = Field(
        default=bool(_GUARDRAILS_CFG.get("enable_live_news_grounding", False)),
        description="Attach a Google Search grounded macro news specialist to the ADK coordinator",
    )
    enable_model_armor: bool = Field(
        default=bool(_GUARDRAILS_CFG.get("enable_model_armor", False)),
        description="Screen prompts with a Model Armor template in addition to the in-process guardrails",
    )
    model_armor_template: str = Field(
        default="",
        description="Model Armor template resource name: projects/<p>/locations/<l>/templates/<id>",
    )
    model_armor_timeout_seconds: float = Field(
        default=float(_GUARDRAILS_CFG.get("model_armor_timeout_seconds", 3.0)),
        description="Per-call timeout for Model Armor screening",
    )
    model_armor_fail_closed: bool = Field(
        default=bool(_GUARDRAILS_CFG.get("model_armor_fail_closed", False)),
        description="Reject prompts when Model Armor is unavailable (default: continue with in-process guardrails)",
    )

    # Observability & Audit Logging
    log_level: str = Field(
        default="INFO",
        description="Root log level for standard library and uvicorn loggers.",
    )
    enable_cloud_trace: bool = Field(default=True, description="Export OpenTelemetry traces to Cloud Trace")
    bigquery_dataset_id: str = Field(default="ira_financial_intelligence", description="BigQuery dataset")
    pubsub_topic_id: str = Field(default="ira-research-events", description="Cloud Pub/Sub broadcast topic")

    # Agent Surfaces
    enable_adk_web: bool = Field(
        default=False,
        description="Mount the ADK developer UI and REST surface under /adk when True.",
    )

    # Circuit Breaker Configuration
    circuit_breaker_failure_threshold: int = Field(default=5)
    circuit_breaker_recovery_timeout_seconds: int = Field(default=60)

    @property
    def allowed_audiences(self) -> tuple[str, ...]:
        """Return configured OIDC token audiences as a tuple."""
        return tuple(a.strip() for a in self.auth_allowed_audiences.split(",") if a.strip())

    @model_validator(mode="after")
    def _require_token_audience_in_production(self) -> "Settings":
        """Enforce non-empty OIDC audience configuration when running in production."""
        if self.environment == "production" and not self.allowed_audiences:
            raise ValueError(
                "ENVIRONMENT=production requires AUTH_ALLOWED_AUDIENCES to be set "
                "(comma-separated OIDC token audiences, e.g. the Cloud Run service URL "
                "and any configured custom audiences)."
            )
        return self

    @model_validator(mode="after")
    def _require_compliant_sec_user_agent_when_live(self) -> "Settings":
        """Enforce a compliant SEC.gov User-Agent header when OFFLINE_MODE is disabled."""
        if not self.offline_mode and (
            self.sec_edgar_user_agent == SAMPLE_SEC_USER_AGENT
            or "@" not in self.sec_edgar_user_agent
        ):
            raise ValueError(
                "OFFLINE_MODE=false requires a compliant SEC_EDGAR_USER_AGENT with your "
                "organisation name and a monitored contact address, e.g. "
                f"'IRA Research admin@example.com'. Got: {self.sec_edgar_user_agent!r}"
            )
        return self

    @model_validator(mode="after")
    def _reject_placeholder_project_in_production(self) -> "Settings":
        """Reject the default placeholder GCP project ID when running in production."""
        if self.environment == "production" and self.gcp_project_id == SAMPLE_GCP_PROJECT_ID:
            raise ValueError(
                "ENVIRONMENT=production requires GCP_PROJECT_ID to name the real "
                f"project; it is still the placeholder {SAMPLE_GCP_PROJECT_ID!r}."
            )
        return self

    @model_validator(mode="after")
    def _validate_enumerated_settings(self) -> "Settings":
        """Reject unsupported DLP backends and safety thresholds early."""
        if self.dlp_backend not in {"regex", "cloud_dlp"}:
            raise ValueError(f"DLP_BACKEND must be 'regex' or 'cloud_dlp', got {self.dlp_backend!r}.")
        allowed_thresholds = {
            "BLOCK_LOW_AND_ABOVE",
            "BLOCK_MEDIUM_AND_ABOVE",
            "BLOCK_ONLY_HIGH",
            "BLOCK_NONE",
            "OFF",
        }
        if self.safety_harm_block_threshold not in allowed_thresholds:
            raise ValueError(
                "SAFETY_HARM_BLOCK_THRESHOLD must be one of "
                f"{sorted(allowed_thresholds)}, got {self.safety_harm_block_threshold!r}."
            )
        if self.enable_model_armor and self.model_armor_template.count("/") < 5:
            raise ValueError(
                "ENABLE_MODEL_ARMOR=true requires MODEL_ARMOR_TEMPLATE set to "
                "'projects/<project>/locations/<location>/templates/<id>'."
            )
        return self


settings = Settings()
