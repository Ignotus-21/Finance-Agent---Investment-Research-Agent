output "dashboard_id" {
  description = "Applied Cloud Monitoring dashboard resource ID"
  value       = google_monitoring_dashboard.ira_observability.id
}

output "slo_ids" {
  description = "The three SLOs backing the Definition of Done thresholds"
  value = {
    availability = google_monitoring_slo.availability.id
    latency_p95  = google_monitoring_slo.latency_p95.id
    error_rate   = google_monitoring_slo.error_rate.id
  }
}

output "notification_channel_id" {
  description = "On-call notification channel used by every alert policy"
  value       = google_monitoring_notification_channel.oncall_email.id
}
