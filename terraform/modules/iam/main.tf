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

  # Deliberately absent: roles/bigquery.dataEditor. It was granted
  # project-wide for "streaming audit logs & metrics into BigQuery", a write
  # no code ever made - the runtime has no BigQuery client. Audit records now
  # reach BigQuery through a Cloud Logging sink that writes as its own
  # identity, scoped to the one dataset. Keeping the grant would have left the
  # runtime with standing write access to every dataset in the project in
  # exchange for nothing.
  #
  # Also absent: roles/pubsub.publisher. The runtime does publish now, but to
  # exactly one topic, so the grant belongs on that topic - see
  # google_pubsub_topic_iam_member.runtime_publisher in the root module. A
  # project-wide role here would let a prompt-injected agent publish into any
  # topic in the project, including ones driving other systems.
}

resource "google_project_iam_member" "ira_sa_roles" {
  # NOTE: the accessor prefix is the singular `local.`, not `locals.`.
  for_each = toset(local.runtime_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.ira_runtime_sa.email}"
}

# --- Caller identity -------------------------------------------------------
# A second service account that exists only to be impersonated by the humans
# and pipelines that need to *call* the service.
#
# Calling an IAM-protected Cloud Run service needs an ID token whose audience
# the service accepts, and a Google user account cannot mint one: the token
# `gcloud auth print-identity-token` issues for a user carries the gcloud OAuth
# client as its audience, and --audiences is rejected unless the call also
# impersonates a service account. Impersonation is the documented route.
#
# The runtime SA would work and must not be used for it. It holds
# aiplatform.user, secretmanager.secretAccessor, dlp.user and publish rights on
# the research topic; giving an analyst token-creator on it to obtain one
# Authorization header would hand them the entire blast radius of the service.
# This one holds run.invoker, from the Cloud Run module, and nothing else -
# which is also why the Streamlit console runs as it.
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
