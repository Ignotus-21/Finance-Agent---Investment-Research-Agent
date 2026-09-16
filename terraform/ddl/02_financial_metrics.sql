-- BigQuery DDL: Time-Series Verified Financial Metrics Table
-- Stores deterministic financial ratios with complete line-item citation provenance.

CREATE TABLE IF NOT EXISTS `ira_financial_intelligence.financial_time_series_metrics` (
  metric_id STRING NOT NULL OPTIONS(description="Unique UUID for metric observation"),
  ticker STRING NOT NULL OPTIONS(description="Equity ticker symbol"),
  fiscal_year INT64 NOT NULL OPTIONS(description="Fiscal reporting year"),
  fiscal_period STRING NOT NULL OPTIONS(description="Fiscal period: FY, Q1, Q2, Q3, Q4"),
  metric_name STRING NOT NULL OPTIONS(description="Canonical metric name (e.g. yoy_revenue_growth_pct, operating_margin_current_pct)"),
  metric_value FLOAT64 NOT NULL OPTIONS(description="Deterministic calculated ratio or percentage"),
  unit STRING NOT NULL OPTIONS(description="Unit of measurement: percentage, bps, currency_usd, ratio_multiple"),
  formula_applied STRING NOT NULL OPTIONS(description="Mathematical formula used by FinancialCalculator"),
  source_filing STRING NOT NULL OPTIONS(description="Primary disclosure document (e.g. Form 10-K, 10-Q)"),
  accession_number STRING OPTIONS(description="SEC EDGAR accession number"),
  verified_at TIMESTAMP NOT NULL OPTIONS(description="Verification timestamp")
)
CLUSTER BY ticker, metric_name
OPTIONS(
  description="Historical registry of verified deterministic financial metrics extracted from primary SEC filings."
);
