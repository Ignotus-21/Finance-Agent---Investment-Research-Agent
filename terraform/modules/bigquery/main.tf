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

# Compliance audit export: Cloud Logging sink -> BigQuery.
#
# This replaces a hand-declared `compliance_audit_log` table that could never
# have received a row. Nothing in the application ever opened a BigQuery
# client; `AuditLogger` writes structured JSON to stdout, which Cloud Run
# ingests into Cloud Logging. The export therefore belongs here, as a sink,
# and that is strictly better than an in-process client would have been:
#
#   * The application cannot skip it, and a BigQuery outage cannot fail a
#     research request. An audit record the request path can drop is not an
#     audit record.
#   * Cloud Logging still holds the record independently, so reconfiguring the
#     sink loses nothing.
#
# The sink owns its destination table - `run_googleapis_com_stdout`, with the
# standard LogEntry schema. The audit fields live under
# `jsonPayload.compliance_metadata`; see `docs/operational_runbook.md` for the
# query that projects them back into columns.
resource "google_logging_project_sink" "compliance_audit_export" {
  name        = "ira-compliance-audit-${var.environment}"
  project     = var.project_id
  description = "Exports IRA compliance audit records from Cloud Logging to BigQuery."
  destination = "bigquery.googleapis.com/projects/${var.project_id}/datasets/${google_bigquery_dataset.ira_dataset.dataset_id}"

  # Narrow on purpose. A sink filtered only by service would export every
  # request log and access log into the compliance dataset, which inflates
  # cost and buries the records that are actually subject to retention.
  filter = <<-EOT
    resource.type="cloud_run_revision"
    resource.labels.service_name="${var.cloud_run_service_name}"
    jsonPayload.compliance_metadata:*
  EOT

  # Day-partitioned so retention and cost controls are expressible in SQL.
  bigquery_options {
    use_partitioned_tables = true
  }

  # Gives the sink its own writer identity instead of the shared, broadly
  # scoped logs-writer default. Required for the dataset-scoped grant below.
  unique_writer_identity = true
}

# The sink's identity is created with the sink, so the grant is dataset-scoped
# rather than project-scoped: this principal can write to exactly this dataset.
resource "google_bigquery_dataset_iam_member" "audit_sink_writer" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.ira_dataset.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = google_logging_project_sink.compliance_audit_export.writer_identity
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
