# ---------------------------------------------------------------------------
# Google Artifact Registry - container image repository for the IRA service.
#
# cloudbuild.yaml already pushes to
#   $_REGION-docker.pkg.dev/$PROJECT_ID/ira-repo/ira-service
# but the repository itself was never declared in Terraform, so a fresh project
# required someone to create it by hand before the first build could succeed.
# That is exactly the manual step the capstone's "zero-touch IaC" requirement
# rules out. This module closes that loop.
# ---------------------------------------------------------------------------

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

  # CMEK. Reuses the KMS key already created by the secret_manager module
  # rather than standing up a second key ring - one key, one rotation
  # schedule, one place to revoke if the project is ever compromised.
  kms_key_name = var.kms_key_id

  docker_config {
    # Tags stay mutable so cloudbuild can move `:latest`. Traceability comes
    # from the immutable :$COMMIT_SHA tag that every deploy actually pins.
    immutable_tags = false
  }

  # Storage in a container registry grows without bound unless something
  # prunes it. These policies are ordered most-specific first.
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
}

# ---------------------------------------------------------------------------
# KMS access for the Artifact Registry service agent.
# Without this the repository cannot encrypt layers and creation fails with a
# permission error that does not name the missing binding.
# ---------------------------------------------------------------------------
resource "google_kms_crypto_key_iam_member" "artifact_registry_cmek" {
  crypto_key_id = var.kms_key_id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-artifactregistry.iam.gserviceaccount.com"
}

# ---------------------------------------------------------------------------
# Least-privilege repository IAM.
#
# Deliberately NOT granted at project level - these bindings are scoped to the
# single repository, so a compromised build cannot reach other repositories.
# ---------------------------------------------------------------------------

# Cloud Build pushes images.
resource "google_artifact_registry_repository_iam_member" "cloudbuild_writer" {
  project    = var.project_id
  location   = google_artifact_registry_repository.ira_containers.location
  repository = google_artifact_registry_repository.ira_containers.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${data.google_project.current.number}@cloudbuild.gserviceaccount.com"
}

# The Cloud Run service agent pulls images at revision-create time. This is the
# agent, NOT the runtime service account - a common mix-up that surfaces as
# "image not found" on deploy even though the image exists.
resource "google_artifact_registry_repository_iam_member" "cloud_run_reader" {
  project    = var.project_id
  location   = google_artifact_registry_repository.ira_containers.location
  repository = google_artifact_registry_repository.ira_containers.name
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:service-${data.google_project.current.number}@serverless-robot-prod.iam.gserviceaccount.com"
}
