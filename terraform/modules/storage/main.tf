# ---------------------------------------------------------------------------
# Secure Cloud Storage buckets.
#
# Two buckets with deliberately different postures:
#   1. research-briefs - compliance artefact. CMEK, versioned, retention-locked
#      against deletion, long lifecycle. This is evidence.
#   2. eval-artifacts  - CI scratch. CMEK and private, but short lifecycle and
#      no retention policy, because nothing here is evidentiary.
#
# Applying the compliance posture to both would make CI unable to clean up
# after itself; applying the CI posture to both would lose audit evidence.
# ---------------------------------------------------------------------------

data "google_storage_project_service_account" "gcs_agent" {
  project = var.project_id
}

# CMEK prerequisite: the Cloud Storage service agent must be able to use the
# key. Without this binding, bucket creation fails with a generic
# "permission denied on key" that does not identify the missing principal.
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

  # Blocks ACLs entirely so access is governed by IAM alone. Object ACLs are
  # the usual root cause of "public bucket" incidents.
  uniform_bucket_level_access = true

  # Belt and braces: even a future IAM mistake cannot make this public.
  public_access_prevention = "enforced"

  # Recovers from an accidental overwrite of a published brief.
  versioning {
    enabled = true
  }

  encryption {
    default_kms_key_name = var.kms_key_id
  }

  # Regulatory hold: objects cannot be deleted for 7 years. Note this is NOT
  # locked (`retention_policy.is_locked`) - locking is irreversible and would
  # make the bucket undestroyable, which is wrong for a capstone environment.
  # Set is_locked = true for a genuine production compliance deployment.
  retention_policy {
    retention_period = var.brief_retention_seconds
    is_locked        = false
  }

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

# ---------------------------------------------------------------------------
# Least-privilege bucket IAM.
#
# objectAdmin, not admin: the runtime can write and read objects but cannot
# change bucket configuration, delete the bucket, or alter IAM.
# ---------------------------------------------------------------------------
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
