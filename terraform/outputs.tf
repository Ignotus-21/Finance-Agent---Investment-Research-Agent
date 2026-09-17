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
