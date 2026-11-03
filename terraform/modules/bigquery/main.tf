resource "google_bigquery_dataset" "ira_dataset" {
  dataset_id                 = var.dataset_id
  friendly_name              = "IRA Financial Intelligence & Audit Dataset"
  description                = "Immutable storage for multi-agent compliance audits and verified financial metrics."
  location                   = var.region
  project                    = var.project_id
  delete_contents_on_destroy = var.environment != "production"

  labels = {
    env        = "production"
    workload   = "financial-intelligence"
    governance = "finra-rule-2241"
  }
}

resource "google_logging_project_sink" "compliance_audit_export" {
  name        = "ira-compliance-audit-${var.environment}"
  project     = var.project_id
  description = "Exports IRA compliance audit records from Cloud Logging to BigQuery."
  destination = "bigquery.googleapis.com/projects/${var.project_id}/datasets/${google_bigquery_dataset.ira_dataset.dataset_id}"

  filter = <<-EOT
    resource.type="cloud_run_revision"
    resource.labels.service_name="${var.cloud_run_service_name}"
    jsonPayload.compliance_metadata:*
  EOT

  # Day-partitioned so retention and cost controls are expressible in SQL.
  bigquery_options {
    use_partitioned_tables = true
  }

  unique_writer_identity = true
}

resource "google_bigquery_dataset_iam_member" "audit_sink_writer" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.ira_dataset.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = google_logging_project_sink.compliance_audit_export.writer_identity
}
