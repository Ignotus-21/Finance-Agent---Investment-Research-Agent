output "kms_key_id" {
  value = google_kms_crypto_key.ira_crypto_key.id
}

output "market_api_secret_id" {
  value = google_secret_manager_secret.market_api_key.secret_id
}
