data "google_project" "current" {
  project_id = var.project_id
}

resource "google_artifact_registry_repository" "ira_containers" {
  provider = google

  project       = var.project_id
  location      = var.region
  repository_id = var.repository_id
  description   = "Immutable container images for the IRA multi-agent service."
  format        = "DOCKER"

  kms_key_name = var.kms_key_id

  docker_config {
    immutable_tags = false
  }

  cleanup_policies {
    id     = "keep-recent-releases"
    action = "KEEP"
    most_recent_versions {
      keep_count = var.keep_recent_versions
    }
  }

  cleanup_policies {
    id     = "delete-untagged-after-30-days"
    action = "DELETE"
    condition {
      tag_state  = "UNTAGGED"
      older_than = "2592000s" # 30 days
    }
  }

  labels = {
    environment = var.environment
    component   = "container-registry"
    managed-by  = "terraform"
  }

  depends_on = [google_kms_crypto_key_iam_member.artifact_registry_cmek]
}

resource "google_kms_crypto_key_iam_member" "artifact_registry_cmek" {
  crypto_key_id = var.kms_key_id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-artifactregistry.iam.gserviceaccount.com"
}

# Cloud Build pushes images.
resource "google_artifact_registry_repository_iam_member" "cloudbuild_writer" {
  project    = var.project_id
  location   = google_artifact_registry_repository.ira_containers.location
  repository = google_artifact_registry_repository.ira_containers.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${data.google_project.current.number}@cloudbuild.gserviceaccount.com"
}

resource "google_artifact_registry_repository_iam_member" "cloud_run_reader" {
  project    = var.project_id
  location   = google_artifact_registry_repository.ira_containers.location
  repository = google_artifact_registry_repository.ira_containers.name
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:service-${data.google_project.current.number}@serverless-robot-prod.iam.gserviceaccount.com"
}
