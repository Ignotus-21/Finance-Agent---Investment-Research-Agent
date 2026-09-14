output "service_url" {
  value = google_cloud_run_v2_service.ira_service.uri
}

output "service_name" {
  value = google_cloud_run_v2_service.ira_service.name
}
