# ---------------------------------------------------------------------------
# Cloud KMS Customer-Managed Encryption Key (CMEK) & Secret Manager
# ---------------------------------------------------------------------------

data "google_project" "current" {
  project_id = var.project_id
}

resource "google_kms_key_ring" "ira_keyring" {
  name     = "ira-keyring"
  location = var.region
  project  = var.project_id
}

resource "google_kms_crypto_key" "ira_crypto_key" {
  name            = "ira-cmek-key"
  key_ring        = google_kms_key_ring.ira_keyring.id
  rotation_period = "7776000s" # 90-day automatic key rotation

  lifecycle {
    prevent_destroy = false
  }
}

resource "google_kms_crypto_key_iam_member" "secret_manager_cmek" {
  crypto_key_id = google_kms_crypto_key.ira_crypto_key.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-secretmanager.iam.gserviceaccount.com"
}

# CMEK-protected secret for third-party market data credentials.
resource "google_secret_manager_secret" "market_api_key" {
  secret_id = "ira-market-data-api-key"
  project   = var.project_id

  replication {
    user_managed {
      replicas {
        location = var.region
        customer_managed_encryption {
          kms_key_name = google_kms_crypto_key.ira_crypto_key.id
        }
      }
    }
  }

  depends_on = [google_kms_crypto_key_iam_member.secret_manager_cmek]
}
