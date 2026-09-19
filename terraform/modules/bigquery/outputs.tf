output "dataset_id" {
  value = google_bigquery_dataset.ira_dataset.dataset_id
}

output "audit_table_id" {
  description = "Table the logging sink creates on first export. Owned by the sink, LogEntry schema; audit fields are under jsonPayload.compliance_metadata."
  value       = "run_googleapis_com_stdout"
}

output "audit_sink_writer_identity" {
  description = "Principal the sink writes as; granted dataEditor on this dataset only"
  value       = google_logging_project_sink.compliance_audit_export.writer_identity
}
