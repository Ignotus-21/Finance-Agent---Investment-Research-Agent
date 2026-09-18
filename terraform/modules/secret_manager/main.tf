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

# There is deliberately no secret here for the SEC EDGAR contact string.
#
# `ira-sec-edgar-contact` used to be declared in this module and was never wired
# to anything. It could not have been: a User-Agent header is transmitted in
# cleartext on every request to sec.gov, so it is not confidential, and routing
# it through Secret Manager would have bought a cold-start secret fetch and an
# extra IAM surface in exchange for no secrecy at all. It is now a plain env var
# on the Cloud Run revision (see modules/cloud_run/main.tf), where an operator
# debugging a 403 from sec.gov can actually read it.
