"""
Application Configuration Module using Pydantic Settings.
Loads baseline defaults from configs/settings.yaml and overrides via
environment variables or Secret Manager mounts.
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

    # Model Tier & Reasoning Settings
    coordinator_model: str = Field(
        default=_MODELS_CFG.get("coordinator_model", "gemini-2.5-pro"),
        description="Model for root planner & synthesis",
    )
    extraction_model: str = Field(
        default=_MODELS_CFG.get("extraction_model", "gemini-2.5-flash"),
        description="Model for high-throughput parsing",
    )
    temperature: float = Field(default=0.1, description="Low temperature for deterministic financial output")

    # Financial Ingestion & SEC Rate Limiting
    offline_mode: bool = Field(
        default=True,
        description="Serve SEC data from bundled fixtures when True; query live data.sec.gov when False.",
    )
    sec_edgar_user_agent: str = Field(
        default=SAMPLE_SEC_USER_AGENT,
        description="Compliant SEC.gov User-Agent header identifying organization and contact email.",
    )
    sec_rate_limit_per_sec: float = Field(default=8.0, description="Max SEC requests/sec (cap is 10)")
    sec_http_timeout_seconds: float = Field(
        default=20.0, description="Per-request timeout for live SEC EDGAR calls"
    )
    sec_http_max_retries: int = Field(
        default=3, description="Retry attempts for SEC 429/5xx responses"
    )

    # Context Caching & Budget Caps
    context_cache_ttl_minutes: int = Field(default=60, description="Gemini context cache TTL in minutes")
    max_brief_cost_usd: float = Field(default=0.25, description="Target max inference cost per research brief")

    # Security, Privacy & DLP
    auth_allowed_audiences: str = Field(
        default="",
        description="Comma-separated audiences accepted on incoming Google-signed OIDC ID tokens.",
    )
    enable_dlp_masking: bool = Field(default=True, description="Enable regex PII redaction on inbound prompts")
    enforce_guardrails: bool = Field(default=True, description="Enforce pre-execution prompt injection filter")

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


settings = Settings()
