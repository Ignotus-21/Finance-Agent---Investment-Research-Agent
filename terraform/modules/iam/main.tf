# Dedicated Least-Privilege Service Account for the IRA Multi-Agent Runtime
resource "google_service_account" "ira_runtime_sa" {
  account_id   = var.service_account_name
  display_name = "IRA Multi-Agent Runtime Service Account"
  description  = "Least-privilege service account executing Cloud Run multi-agent workloads and audit logging."
  project      = var.project_id
}

locals {
  runtime_roles = [
    "roles/aiplatform.user",              # Vertex AI Gemini model invocation & context caching
    "roles/bigquery.dataEditor",          # Streaming audit logs & metrics into BigQuery
    "roles/logging.logWriter",            # Tamper-evident structured Cloud Logging
    "roles/cloudtrace.agent",             # OpenTelemetry distributed trace export
    "roles/secretmanager.secretAccessor", # Access to encrypted API credentials
    "roles/pubsub.publisher",             # Publishing research completion events
    "roles/dlp.user"                      # Data Loss Prevention inspection and redaction
  ]
}

resource "google_project_iam_member" "ira_sa_roles" {
  # NOTE: the accessor prefix is the singular `local.`, not `locals.`.
  for_each = toset(local.runtime_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.ira_runtime_sa.email}"
}
