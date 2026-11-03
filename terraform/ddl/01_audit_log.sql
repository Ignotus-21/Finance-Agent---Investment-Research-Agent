-- =============================================================================
-- Autonomous Investment Research Intelligence Agent (IRA)
-- Table: compliance_audit_log
-- Description: Immutable compliance audit log for institutional equity research
--              queries (FINRA Rule 2241 / SEC Rule 17a-4 retention).
-- =============================================================================

CREATE TABLE IF NOT EXISTS `ira_financial_intelligence.compliance_audit_log` (
  audit_id STRING NOT NULL OPTIONS(description="Unique audit event UUID v4"),
  timestamp TIMESTAMP NOT NULL OPTIONS(description="UTC execution timestamp"),
  user_id STRING NOT NULL OPTIONS(description="Verified OIDC caller identity or service principal"),
  ticker STRING NOT NULL OPTIONS(description="Target public equity ticker symbol"),
  fiscal_year INT64 NOT NULL OPTIONS(description="Fiscal reporting year analyzed"),
  prompt_hash STRING NOT NULL OPTIONS(description="SHA-256 digest of the sanitized user request"),
  tools_called ARRAY<STRING> OPTIONS(description="Ordered list of MCP and deterministic tools invoked"),
  model_id STRING NOT NULL OPTIONS(description="Primary coordinator model or execution engine identifier"),
  latency_ms INT64 NOT NULL OPTIONS(description="Total end-to-end execution latency in milliseconds"),
  total_tokens INT64 NOT NULL OPTIONS(description="Total prompt and completion tokens consumed"),
  cost_usd FLOAT64 NOT NULL OPTIONS(description="Estimated inference cost in USD"),
  guardrail_verdict STRING NOT NULL OPTIONS(description="Guardrail classification verdict: PASS, REJECT_INJECTION, REJECT_SCOPE"),
  citations_count INT64 NOT NULL OPTIONS(description="Count of verified primary-source citations attached"),
  spans JSON OPTIONS(description="Serialized OpenTelemetry execution span hierarchy")
)
PARTITION BY DATE(timestamp)
CLUSTER BY ticker, guardrail_verdict
OPTIONS (
  description = "Immutable compliance audit log for institutional equity research requests",
  require_partition_filter = false
);
