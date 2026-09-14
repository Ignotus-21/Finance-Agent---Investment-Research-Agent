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
