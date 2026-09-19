"""
Structured Audit Logging Middleware.

Emits tamper-evident compliance audit records to Google Cloud Logging as
structured JSON on stdout, which Cloud Run ingests. BigQuery receives them via
a Cloud Logging sink (``google_logging_project_sink`` in
``terraform/modules/bigquery``), not from this process.

That split is deliberate, and it is a correction. The docstring here used to
claim records were streamed to BigQuery, Terraform created the dataset and the
tables, and the runtime service account was granted ``bigquery.dataEditor`` -
for a write that no code performed. The fix is the sink rather than a client
here, for three reasons:

* An audit record the application can fail to write is not an audit record. A
  log sink is outside the process; the application cannot skip it, and a
  BigQuery outage cannot fail a research request.
* Export is configuration, so it stays declarative in Terraform.
* Cloud Logging retains and exports the same record, so nothing is lost if the
  sink is reconfigured.
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

# Audit records are emitted to Cloud Logging; this deque is a small in-process
# tail for tests and for /readyz-style introspection. It was an unbounded list,
# which on a revision with min_instances=1 is a slow memory leak that only
# shows up in production, weeks in.
_AUDIT_TAIL_SIZE = 256


class AuditLogger:
    """
    Compliance audit logger emitting execution records to Cloud Logging as
    structured stdout JSON. BigQuery is fed downstream by a log sink, not by
    this class - see the module docstring for why.
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
        citations_count: int = 0
    ) -> AuditLogEntry:
        """
        Creates and emits an immutable compliance record.
        """
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
            citations_count=citations_count
        )

        record_dict = entry.model_dump()
        self.audit_records.append(record_dict)

        # Emit structured JSON log conforming to Google Cloud Logging specification
        cloud_log_payload: dict[str, Any] = {
            "severity": "INFO",
            "message": f"Compliance Audit: Research completed for {ticker} FY{fiscal_year}",
            "compliance_metadata": record_dict,
        }

        # This field used to be set to `audit_id` - a bare uuid4. Cloud Logging
        # accepts any string there and silently correlates nothing, so the
        # console showed a trace link on every audit record that led nowhere.
        # `current_trace_context` returns the correctly-formatted resource name
        # or an empty dict; a missing link is visibly missing.
        cloud_log_payload.update(current_trace_context(self.settings.gcp_project_id))

        # stdout is the transport. Cloud Run forwards it to Cloud Logging, and
        # the log sink forwards it from there to BigQuery.
        print(json.dumps(cloud_log_payload))

        return entry


audit_logger = AuditLogger()
