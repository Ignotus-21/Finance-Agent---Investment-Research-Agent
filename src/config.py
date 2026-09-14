"""
Application Configuration Module using Pydantic Settings.
Manages environment variables, model tiers, rate limits, and cloud endpoints.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    sec_edgar_user_agent: str = Field(
        default="SampleInstitutionalResearch AdminContact@samplecompany.com",
        description="Mandatory compliant User-Agent for SEC.gov"
    )
    sec_rate_limit_per_sec: float = Field(default=8.0, description="Max SEC requests/sec (cap is 10)")

    # Context Caching & Budget Caps
    context_cache_ttl_minutes: int = Field(default=60, description="Gemini context cache TTL in minutes")
    max_brief_cost_usd: float = Field(default=0.25, description="Target max inference cost per research brief")

    # Security, Privacy & DLP
    enable_dlp_masking: bool = Field(default=True, description="Enable Cloud DLP redaction middleware")
    enforce_guardrails: bool = Field(default=True, description="Enforce pre-execution prompt injection filter")

    # Observability & Audit Logging
    enable_cloud_trace: bool = Field(default=True, description="Export OpenTelemetry traces to Cloud Trace")
    bigquery_dataset_id: str = Field(default="ira_financial_intelligence", description="BigQuery dataset")
    pubsub_topic_id: str = Field(default="ira-research-events", description="Cloud Pub/Sub broadcast topic")

    # Circuit Breaker Configuration
    circuit_breaker_failure_threshold: int = Field(default=5)
    circuit_breaker_recovery_timeout_seconds: int = Field(default=60)


settings = Settings()
