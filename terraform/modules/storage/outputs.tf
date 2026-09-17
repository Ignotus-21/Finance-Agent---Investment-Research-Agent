output "research_briefs_bucket" {
  description = "Name of the evidentiary research brief archive bucket"
  value       = google_storage_bucket.research_briefs.name
}

output "eval_artifacts_bucket" {
  description = "Name of the CI evaluation artefact bucket"
  value       = google_storage_bucket.eval_artifacts.name
}
