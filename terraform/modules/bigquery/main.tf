resource "google_bigquery_dataset" "ira_dataset" {
  dataset_id                 = var.dataset_id
  friendly_name              = "IRA Financial Intelligence & Audit Dataset"
  description                = "Immutable storage for multi-agent compliance audits and verified financial metrics."
  location                   = var.region
  project                    = var.project_id
  delete_contents_on_destroy = false

  labels = {
    env        = "production"
    workload   = "financial-intelligence"
    governance = "finra-rule-2241"
  }
}

# Immutable Audit Log Table for Compliance & Provenance
resource "google_bigquery_table" "audit_log_table" {
  dataset_id = google_bigquery_dataset.ira_dataset.dataset_id
  table_id   = "compliance_audit_log"
  project    = var.project_id

  time_partitioning {
    type  = "DAY"
    field = "timestamp"
  }

  clustering = ["ticker", "user_id", "guardrail_verdict"]

  schema = jsonencode([
    { name = "audit_id", type = "STRING", mode = "REQUIRED", description = "Unique UUID of research query" },
    { name = "timestamp", type = "TIMESTAMP", mode = "REQUIRED", description = "Execution UTC timestamp" },
    { name = "user_id", type = "STRING", mode = "REQUIRED", description = "Masked identity of requesting analyst" },
    { name = "ticker", type = "STRING", mode = "REQUIRED", description = "Equity ticker symbol" },
    { name = "fiscal_year", type = "INTEGER", mode = "REQUIRED", description = "Fiscal year evaluated" },
    { name = "prompt_hash", type = "STRING", mode = "REQUIRED", description = "SHA-256 hash of query" },
    { name = "tools_called", type = "STRING", mode = "REPEATED", description = "List of tools invoked" },
    { name = "model_id", type = "STRING", mode = "REQUIRED", description = "Coordinator model version" },
    { name = "latency_ms", type = "INTEGER", mode = "REQUIRED", description = "Total latency in ms" },
    { name = "total_tokens", type = "INTEGER", mode = "REQUIRED", description = "Token consumption count" },
    { name = "cost_usd", type = "FLOAT", mode = "REQUIRED", description = "Incurred token cost in USD" },
    { name = "guardrail_verdict", type = "STRING", mode = "REQUIRED", description = "Security classifier outcome" },
    { name = "citations_count", type = "INTEGER", mode = "REQUIRED", description = "Number of verified citations" }
  ])
}

# Time-Series Verified Financial Metrics Table
resource "google_bigquery_table" "metrics_table" {
  dataset_id = google_bigquery_dataset.ira_dataset.dataset_id
  table_id   = "financial_time_series_metrics"
  project    = var.project_id

  clustering = ["ticker", "metric_name"]

  schema = jsonencode([
    { name = "metric_id", type = "STRING", mode = "REQUIRED" },
    { name = "ticker", type = "STRING", mode = "REQUIRED" },
    { name = "fiscal_year", type = "INTEGER", mode = "REQUIRED" },
    { name = "fiscal_period", type = "STRING", mode = "REQUIRED" },
    { name = "metric_name", type = "STRING", mode = "REQUIRED" },
    { name = "metric_value", type = "FLOAT", mode = "REQUIRED" },
    { name = "unit", type = "STRING", mode = "REQUIRED" },
    { name = "formula_applied", type = "STRING", mode = "REQUIRED" },
    { name = "source_filing", type = "STRING", mode = "REQUIRED" },
    { name = "accession_number", type = "STRING", mode = "NULLABLE" },
    { name = "verified_at", type = "TIMESTAMP", mode = "REQUIRED" }
  ])
}
