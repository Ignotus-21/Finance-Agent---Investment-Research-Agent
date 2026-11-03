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
    "roles/logging.logWriter",            # Tamper-evident structured Cloud Logging
    "roles/cloudtrace.agent",             # OpenTelemetry distributed trace export
    "roles/secretmanager.secretAccessor", # Access to encrypted API credentials
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

resource "google_service_account" "ira_caller_sa" {
  account_id   = var.caller_service_account_name
  display_name = "IRA Caller Service Account"
  description  = "Impersonated to mint ID tokens for calling the research service. Holds run.invoker only."
  project      = var.project_id
}

resource "google_service_account_iam_member" "ira_caller_token_creators" {
  for_each           = toset(var.token_creator_members)
  service_account_id = google_service_account.ira_caller_sa.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = each.value
}
