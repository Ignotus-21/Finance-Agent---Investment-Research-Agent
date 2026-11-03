data "google_storage_project_service_account" "gcs_agent" {
  project = var.project_id
}

resource "google_kms_crypto_key_iam_member" "gcs_cmek" {
  crypto_key_id = var.kms_key_id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${data.google_storage_project_service_account.gcs_agent.email_address}"
}

# ---------------------------------------------------------------------------
# 1. Research brief archive - immutable evidentiary record.
# ---------------------------------------------------------------------------
resource "google_storage_bucket" "research_briefs" {
  name     = "${var.project_id}-ira-research-briefs-${var.environment}"
  project  = var.project_id
  location = var.region

  uniform_bucket_level_access = true

  public_access_prevention = "enforced"

  # Recovers from an accidental overwrite of a published brief.
  versioning {
    enabled = true
  }

  encryption {
    default_kms_key_name = var.kms_key_id
  }

  retention_policy {
    retention_period = var.brief_retention_seconds
    is_locked        = false
  }

  force_destroy = var.environment != "production"

  # Cost control: briefs are read heavily for ~30 days, then almost never.
  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }

  lifecycle_rule {
    condition {
      age = 365
    }
    action {
      type          = "SetStorageClass"
      storage_class = "COLDLINE"
    }
  }

  # Prune superseded versions; the live object is untouched.
  lifecycle_rule {
    condition {
      num_newer_versions = 5
      with_state         = "ARCHIVED"
    }
    action {
      type = "Delete"
    }
  }

  labels = {
    environment = var.environment
    component   = "research-brief-archive"
    data-class  = "confidential"
    managed-by  = "terraform"
  }

  depends_on = [google_kms_crypto_key_iam_member.gcs_cmek]
}

# ---------------------------------------------------------------------------
# 2. Evaluation artefacts - CI output, short lived.
# ---------------------------------------------------------------------------
resource "google_storage_bucket" "eval_artifacts" {
  name     = "${var.project_id}-ira-eval-artifacts-${var.environment}"
  project  = var.project_id
  location = var.region

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  encryption {
    default_kms_key_name = var.kms_key_id
  }

  # No retention policy: CI must be able to overwrite and delete its own runs.
  lifecycle_rule {
    condition {
      age = var.eval_artifact_retention_days
    }
    action {
      type = "Delete"
    }
  }

  # Lets `terraform destroy` succeed in non-production without a manual purge.
  force_destroy = var.environment != "production"

  labels = {
    environment = var.environment
    component   = "evaluation-artifacts"
    data-class  = "internal"
    managed-by  = "terraform"
  }

  depends_on = [google_kms_crypto_key_iam_member.gcs_cmek]
}

resource "google_storage_bucket_iam_member" "runtime_briefs_writer" {
  bucket = google_storage_bucket.research_briefs.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${var.runtime_service_account_email}"
}

resource "google_storage_bucket_iam_member" "runtime_eval_writer" {
  bucket = google_storage_bucket.eval_artifacts.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${var.runtime_service_account_email}"
}
