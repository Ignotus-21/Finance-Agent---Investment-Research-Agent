# Cloud KMS KeyRing and CryptoKey for Customer Managed Encryption Keys (CMEK)
resource "google_kms_key_ring" "ira_keyring" {
  name     = "ira-keyring"
  location = var.region
  project  = var.project_id
}

resource "google_kms_crypto_key" "ira_crypto_key" {
  name            = "ira-cmek-key"
  key_ring        = google_kms_key_ring.ira_keyring.id
  rotation_period = "7776000s" # 90 days key rotation

  lifecycle {
    prevent_destroy = false
  }
}

# Secret for Third-Party Market Data Credentials
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
}

# Secret for SEC EDGAR Admin Contact Token
resource "google_secret_manager_secret" "sec_contact_secret" {
  secret_id = "ira-sec-edgar-contact"
  project   = var.project_id

  replication {
    auto {}
  }
}
