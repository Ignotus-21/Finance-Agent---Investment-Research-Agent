variable "project_id" {
  description = "The Google Cloud Project ID"
  type        = string
}

variable "region" {
  description = "Artifact Registry location; keep identical to the Cloud Run region so image pulls stay in-region"
  type        = string
}

variable "environment" {
  description = "Deployment environment label"
  type        = string
}

variable "repository_id" {
  description = "Repository name. Must match _ARTIFACT_REPO in cloudbuild.yaml."
  type        = string
  default     = "ira-repo"
}

variable "kms_key_id" {
  description = "Cloud KMS CryptoKey ID used for CMEK encryption of stored image layers"
  type        = string
}

variable "keep_recent_versions" {
  description = "Number of most-recent image versions retained by the cleanup policy"
  type        = number
  default     = 10
}
