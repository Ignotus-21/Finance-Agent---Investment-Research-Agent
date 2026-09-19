variable "project_id" {
  description = "The Google Cloud Project ID"
  type        = string
}

variable "region" {
  description = "Bucket location; matches the Cloud Run region to avoid cross-region egress"
  type        = string
}

variable "environment" {
  description = "Deployment environment; also used to suffix bucket names"
  type        = string
}

variable "kms_key_id" {
  description = "Cloud KMS CryptoKey ID for CMEK encryption at rest"
  type        = string
}

variable "runtime_service_account_email" {
  description = "Service account that reads and writes objects from the Cloud Run runtime"
  type        = string
}

variable "brief_retention_seconds" {
  description = "Minimum retention for archived research briefs. Default 7 years, matching SEC Rule 17a-4 record-keeping expectations."
  type        = number
  default     = 220752000 # 7 years
}

variable "eval_artifact_retention_days" {
  description = "Days before CI evaluation artefacts are deleted"
  type        = number
  default     = 90
}
