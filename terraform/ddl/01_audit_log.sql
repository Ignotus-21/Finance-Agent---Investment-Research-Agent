-- ┌───────────────────────────────────────────────────────────────────────────┐
-- │ NOT PROVISIONED. Reference material only - this file is executed by       │
-- │ nothing, and no Terraform resource creates this table.                    │
-- │                                                                            │
-- │ Removed in #18. Audit records are written as structured JSON on stdout,   │
-- │ ingested by the Cloud Run logging agent, and exported to BigQuery by      │
-- │ `google_logging_project_sink.compliance_audit_export`. That sink creates  │
-- │ and owns its own table (`run_googleapis_com_stdout`) with the LogEntry    │
-- │ schema; the audit fields live under `jsonPayload.compliance_metadata`.    │
-- │ A hand-declared table alongside it stayed permanently empty and implied   │
-- │ the audit trail was empty too.                                            │
-- └───────────────────────────────────────────────────────────────────────────┘

-- BigQuery DDL: Compliance & Research Audit Trail Table
-- Partitioned by DAY on timestamp; Clustered by ticker and user_id for fast audit query scans.

CREATE TABLE IF NOT EXISTS `ira_financial_intelligence.compliance_audit_log` (
  audit_id STRING NOT NULL OPTIONS(description="Unique UUID identifying research query execution"),
  timestamp TIMESTAMP NOT NULL OPTIONS(description="UTC timestamp of query execution"),
  user_id STRING NOT NULL OPTIONS(description="Sanitized and masked user identity (Cloud DLP)"),
  ticker STRING NOT NULL OPTIONS(description="Public equity ticker symbol evaluated"),
  fiscal_year INT64 NOT NULL OPTIONS(description="Fiscal reporting year targeted"),
  prompt_hash STRING NOT NULL OPTIONS(description="SHA-256 hash of the sanitized user prompt"),
  tools_called ARRAY<STRING> OPTIONS(description="List of tool identifiers invoked during reasoning"),
  model_id STRING NOT NULL OPTIONS(description="Primary reasoning model version (e.g. gemini-2.5-pro)"),
  latency_ms INT64 NOT NULL OPTIONS(description="Total round-trip latency in milliseconds"),
  total_tokens INT64 NOT NULL OPTIONS(description="Total token consumption across all agent invocations"),
  cost_usd FLOAT64 NOT NULL OPTIONS(description="Estimated USD cost computed from token consumption and cache hit"),
  guardrail_verdict STRING NOT NULL OPTIONS(description="Security classifier outcome (PASS, REJECT_INJECTION, REJECT_SCOPE)"),
  citations_count INT64 NOT NULL OPTIONS(description="Total count of verifiable line-item citations rendered")
)
PARTITION BY DATE(timestamp)
CLUSTER BY ticker, user_id, guardrail_verdict
OPTIONS(
  description="Immutable compliance audit log capturing every interactive query, latency, and guardrail verdict."
);
