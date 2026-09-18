output "cloud_run_service_url" {
  description = "The fully qualified HTTPS URL of the deployed Cloud Run service"
  value       = module.cloud_run.service_url
}

output "vpc_network_id" {
  description = "Dedicated VPC Network ID"
  value       = module.vpc.network_id
}

output "bigquery_dataset_id" {
  description = "BigQuery Compliance Dataset ID"
  value       = module.bigquery.dataset_id
}

output "runtime_service_account" {
  description = "Least privilege service account executing agent workloads"
  value       = module.iam.service_account_email
}

output "artifact_registry_url" {
  description = "Base docker push/pull URL; must match the image path built by cloudbuild.yaml"
  value       = module.artifact_registry.repository_url
}

output "research_briefs_bucket" {
  description = "CMEK-encrypted bucket archiving generated research briefs"
  value       = module.storage.research_briefs_bucket
}

output "eval_artifacts_bucket" {
  description = "CMEK-encrypted bucket holding CI evaluation artefacts"
  value       = module.storage.eval_artifacts_bucket
}

output "slo_ids" {
  description = "Cloud Monitoring SLOs enforcing the Definition of Done thresholds"
  value       = module.monitoring.slo_ids
}

output "caller_service_account" {
  description = "Impersonate this to mint an ID token the service will accept: `gcloud auth print-identity-token --impersonate-service-account=<this> --audiences=<custom audience>`"
  value       = module.iam.caller_service_account_email
}

output "accepted_token_audiences" {
  description = "Values the service will accept in the aud claim, besides its own run.app URL"
  value       = var.custom_audiences
}

output "research_events_topic" {
  description = "Pub/Sub topic carrying research.brief.completed events"
  value       = google_pubsub_topic.research_events.name
}

output "research_events_subscription" {
  description = "Pull here to verify a deployment is actually emitting events: gcloud pubsub subscriptions pull <this> --auto-ack"
  value       = google_pubsub_subscription.research_events_default.name
}

output "audit_log_sink_writer" {
  description = "Cloud Logging sink identity exporting compliance audit records to BigQuery"
  value       = module.bigquery.audit_sink_writer_identity
}

output "audit_export_table" {
  description = "BigQuery table the audit sink writes to, inside bigquery_dataset_id"
  value       = module.bigquery.audit_table_id
}
