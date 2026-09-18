"""
Application Configuration Module using Pydantic Settings.
Manages environment variables, model tiers, rate limits, and cloud endpoints.
"""

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The placeholder shipped in .env.example and in this module's own default.
# Named so the validator below can reject it by identity rather than by a
# substring guess, and so there is exactly one place to change it.
SAMPLE_SEC_USER_AGENT = "SampleInstitutionalResearch AdminContact@samplecompany.com"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # Application Metadata
    app_name: str = "Autonomous Investment Research Intelligence Agent (IRA)"
    environment: str = Field(default="development", description="development, staging, production")
    debug: bool = Field(default=False)
    api_port: int = Field(default=8080)

    # Google Cloud Platform Settings
    gcp_project_id: str = Field(default="ira-capstone-finance-prod", description="GCP Project ID")
    gcp_region: str = Field(default="us-central1", description="Target GCP Region")

    # Model Tier & Reasoning Settings
    coordinator_model: str = Field(default="gemini-2.5-pro", description="Model for root planner & synthesis")
    extraction_model: str = Field(default="gemini-2.5-flash", description="Model for high-throughput parsing")
    thinking_budget: int = Field(default=2048, description="Thinking budget tokens for Gemini 2.5 Pro")
    temperature: float = Field(default=0.1, description="Low temperature for deterministic financial output")

    # Financial Ingestion & SEC Rate Limiting
    offline_mode: bool = Field(
        default=True,
        description=(
            "When true, SEC data is served from bundled fixtures and no network call is made. "
            "Defaults to true so tests, CI and the evaluation gate stay hermetic and "
            "deterministic; going live against sec.gov is an explicit opt-in."
        ),
    )
    sec_edgar_user_agent: str = Field(
        default=SAMPLE_SEC_USER_AGENT,
        description=(
            "Mandatory compliant User-Agent for SEC.gov. Must include a real contact address: "
            "SEC throttles and then IP-bans requests that do not identify the caller. "
            "Replace the sample value before enabling OFFLINE_MODE=false."
        )
    )
    sec_rate_limit_per_sec: float = Field(default=8.0, description="Max SEC requests/sec (cap is 10)")
    sec_http_timeout_seconds: float = Field(
        default=20.0, description="Per-request timeout for live SEC EDGAR calls"
    )
    sec_http_max_retries: int = Field(
        default=3, description="Retry attempts for SEC 429/5xx responses before giving up"
    )

    # Context Caching & Budget Caps
    context_cache_ttl_minutes: int = Field(default=60, description="Gemini context cache TTL in minutes")
    max_brief_cost_usd: float = Field(default=0.25, description="Target max inference cost per research brief")

    # Security, Privacy & DLP
    auth_expected_audience: str = Field(
        default="",
        description=(
            "Audience the caller's Google-signed ID token must carry. Cloud Run forwards the "
            "Authorization header it authenticated with, so this is the Cloud Run service URL - "
            "read it from `terraform output cloud_run_service_url` after the first apply. "
            "Empty means bearer credentials are accepted without verification, which the "
            "validator below refuses to allow in production."
        ),
    )
    enable_dlp_masking: bool = Field(default=True, description="Enable Cloud DLP redaction middleware")
    enforce_guardrails: bool = Field(default=True, description="Enforce pre-execution prompt injection filter")

    # Observability & Audit Logging
    enable_cloud_trace: bool = Field(default=True, description="Export OpenTelemetry traces to Cloud Trace")
    bigquery_dataset_id: str = Field(default="ira_financial_intelligence", description="BigQuery dataset")
    pubsub_topic_id: str = Field(default="ira-research-events", description="Cloud Pub/Sub broadcast topic")

    # Circuit Breaker Configuration
    circuit_breaker_failure_threshold: int = Field(default=5)
    circuit_breaker_recovery_timeout_seconds: int = Field(default=60)

    @model_validator(mode="after")
    def _require_token_audience_in_production(self) -> "Settings":
        """
        Refuse to start a production revision that cannot verify its callers.

        Without an expected audience the API's bearer check degenerates into
        "the header parses", and the identity written to the audit log is
        whatever the caller typed. Cloud Run IAM still stands in front, but a
        single `allUsers` binding - one click, or one line of Terraform - would
        then be the whole story. Failing at startup makes that impossible to do
        by accident.
        """
        if self.environment == "production" and not self.auth_expected_audience.strip():
            raise ValueError(
                "ENVIRONMENT=production requires AUTH_EXPECTED_AUDIENCE, the Cloud Run "
                "service URL that incoming ID tokens are minted for. Get it from "
                "`terraform output cloud_run_service_url`."
            )
        return self

    @model_validator(mode="after")
    def _reject_placeholder_contact_when_live(self) -> "Settings":
        """
        Refuse to start in live mode without a real SEC contact address.

        SEC.gov throttles, then blocks, callers whose User-Agent does not
        identify them. The block lands on the source IP, and every request this
        service makes leaves through a single VPC connector - so one bad
        deployment costs the whole service its access, and the failure arrives
        later as 403s that look like an outage rather than a config error.

        Offline mode makes no network call, so the value is irrelevant there and
        the placeholder default stays usable for tests, CI and the eval gate.
        """
        if self.offline_mode:
            return self

        contact = self.sec_edgar_user_agent.strip()
        if not contact or contact == SAMPLE_SEC_USER_AGENT or "@" not in contact:
            raise ValueError(
                "OFFLINE_MODE=false requires a real SEC_EDGAR_USER_AGENT containing an "
                "organisation name and a monitored contact address, e.g. "
                "'IRA Research admin@example.com'. Got: "
                f"{self.sec_edgar_user_agent!r}"
            )
        return self


settings = Settings()
