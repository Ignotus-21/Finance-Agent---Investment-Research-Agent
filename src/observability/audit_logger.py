"""
Compliance Audit Logger.
Emits immutable execution records as structured JSON to stdout for ingestion by
Google Cloud Logging and the downstream BigQuery log sink (`ira-compliance-audit-<env>`).
"""

import collections
import datetime
import hashlib
import json
import uuid
from typing import Any

from src.config import Settings
from src.models.audit import AuditLogEntry
from src.observability.tracer import current_trace_context

_AUDIT_TAIL_SIZE = 256


class AuditLogger:
    """
    Compliance audit logger emitting execution records to Cloud Logging as
    structured stdout JSON for routing to BigQuery via the configured log sink.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.audit_records: collections.deque[dict[str, Any]] = collections.deque(
            maxlen=_AUDIT_TAIL_SIZE
        )

    @staticmethod
    def hash_prompt(prompt: str) -> str:
        """Computes SHA-256 fingerprint of sanitized prompt."""
        return hashlib.sha256(prompt.encode("utf-8")).hexdigest()

    async def log_research_execution(
        self,
        ticker: str,
        fiscal_year: int,
        prompt: str,
        user_id: str,
        tools_called: list[str],
        latency_ms: int,
        total_tokens: int,
        cost_usd: float,
        guardrail_verdict: str = "PASS",
        citations_count: int = 0,
    ) -> AuditLogEntry:
        """Creates and emits an immutable compliance record."""
        audit_id = f"audit-{uuid.uuid4().hex[:12]}"
        timestamp = datetime.datetime.now(datetime.UTC).isoformat()
        prompt_hash = self.hash_prompt(prompt)

        entry = AuditLogEntry(
            audit_id=audit_id,
            timestamp=timestamp,
            user_id=user_id,
            ticker=ticker.upper(),
            fiscal_year=fiscal_year,
            prompt_hash=prompt_hash,
            tools_called=tools_called,
            model_id=self.settings.coordinator_model,
            latency_ms=latency_ms,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
            guardrail_verdict=guardrail_verdict,
            citations_count=citations_count,
        )

        record_dict = entry.model_dump()
        self.audit_records.append(record_dict)

        cloud_log_payload: dict[str, Any] = {
            "severity": "INFO",
            "message": f"Compliance Audit: Research completed for {ticker} FY{fiscal_year}",
            "compliance_metadata": record_dict,
        }
        cloud_log_payload.update(current_trace_context(self.settings.gcp_project_id))

        print(json.dumps(cloud_log_payload))

        return entry


audit_logger = AuditLogger()
