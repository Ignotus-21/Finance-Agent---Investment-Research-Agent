output "service_account_email" {
  value = google_service_account.ira_runtime_sa.email
}

output "service_account_id" {
  value = google_service_account.ira_runtime_sa.id
}

output "caller_service_account_email" {
  value = google_service_account.ira_caller_sa.email
}
