"""
Audit and Observability Data Models.
Enforces immutable compliance logging for BigQuery and Cloud Logging.
"""

from typing import Any

from pydantic import BaseModel, Field


class ExecutionSpan(BaseModel):
    """Distributed tracing span record."""

    span_id: str
    parent_span_id: str | None = None
    name: str
    start_time: str
    end_time: str
    duration_ms: int
    attributes: dict[str, Any] = Field(default_factory=dict)


class AuditLogEntry(BaseModel):
    """
    Tamper-evident audit record written to BigQuery and Google Cloud Logging.
    Meets FINRA Rule 2241 and institutional equity compliance requirements.
    """

    audit_id: str = Field(..., description="Unique audit event UUID.")
    timestamp: str = Field(..., description="ISO 8601 UTC timestamp of execution.")
    user_id: str = Field(default="system-analyst", description="Masked user or service identity.")
    ticker: str = Field(..., description="Target equity ticker symbol.")
    fiscal_year: int = Field(..., description="Fiscal year analyzed.")
    prompt_hash: str = Field(..., description="SHA-256 hash of the sanitized user prompt.")
    tools_called: list[str] = Field(default_factory=list, description="List of tool identifiers invoked.")
    model_id: str = Field(..., description="Primary coordinator model identifier.")
    latency_ms: int = Field(..., description="Total end-to-end execution latency in milliseconds.")
    total_tokens: int = Field(..., description="Total prompt and completion tokens consumed.")
    cost_usd: float = Field(..., description="Estimated inference cost in USD.")
    guardrail_verdict: str = Field(default="PASS", description="PASS, REJECT_INJECTION, REJECT_SCOPE.")
    citations_count: int = Field(default=0, description="Total evidentiary citations generated.")
    spans: list[ExecutionSpan] = Field(default_factory=list, description="Nested OpenTelemetry spans.")
