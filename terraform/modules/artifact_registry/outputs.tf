output "repository_id" {
  description = "Artifact Registry repository name"
  value       = google_artifact_registry_repository.ira_containers.repository_id
}

output "repository_url" {
  description = "Base URL for docker push/pull, e.g. us-central1-docker.pkg.dev/<project>/ira-repo"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.ira_containers.repository_id}"
}
