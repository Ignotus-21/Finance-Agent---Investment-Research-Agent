output "dataset_id" {
  value = google_bigquery_dataset.ira_dataset.dataset_id
}

output "audit_table_id" {
  value = google_bigquery_table.audit_log_table.table_id
}

output "metrics_table_id" {
  value = google_bigquery_table.metrics_table.table_id
}
