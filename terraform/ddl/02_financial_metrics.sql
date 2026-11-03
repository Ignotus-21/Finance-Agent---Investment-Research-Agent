-- =============================================================================
-- Autonomous Investment Research Intelligence Agent (IRA)
-- Table: financial_time_series_metrics
-- Description: Historical time-series store for deterministic financial ratios
--              and audited SEC Form 10-K / 10-Q XBRL line-item metrics.
-- =============================================================================

CREATE TABLE IF NOT EXISTS `ira_financial_intelligence.financial_time_series_metrics` (
  record_id STRING NOT NULL OPTIONS(description="Unique metric record UUID v4"),
  recorded_at TIMESTAMP NOT NULL OPTIONS(description="UTC ingestion timestamp"),
  ticker STRING NOT NULL OPTIONS(description="Public equity ticker symbol"),
  cik STRING OPTIONS(description="Zero-padded 10-digit SEC Central Index Key"),
  fiscal_year INT64 NOT NULL OPTIONS(description="Fiscal reporting year"),
  filing_form STRING NOT NULL OPTIONS(description="SEC form type (10-K, 10-Q, 8-K)"),
  accession_number STRING NOT NULL OPTIONS(description="SEC EDGAR filing accession number"),
  metric_name STRING NOT NULL OPTIONS(description="Canonical metric identifier"),
  display_name STRING NOT NULL OPTIONS(description="Human-readable metric title"),
  metric_value NUMERIC NOT NULL OPTIONS(description="Computed Decimal metric value"),
  unit STRING NOT NULL OPTIONS(description="Unit of measurement (percentage, bps, ratio_multiple, currency_usd)"),
  formula_applied STRING NOT NULL OPTIONS(description="Explicit mathematical formula applied"),
  prior_period_value NUMERIC OPTIONS(description="Prior period t-1 comparative value"),
  current_period_value NUMERIC OPTIONS(description="Current period t value"),
  provenance_verified BOOL NOT NULL OPTIONS(description="Whether primary XBRL line-item provenance was verified")
)
PARTITION BY DATE(recorded_at)
CLUSTER BY ticker, fiscal_year, metric_name
OPTIONS (
  description = "Historical store of deterministic financial ratios and XBRL-verified metrics"
);
