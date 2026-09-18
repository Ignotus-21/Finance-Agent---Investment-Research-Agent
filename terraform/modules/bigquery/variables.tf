variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "dataset_id" {
  type    = string
  default = "ira_financial_intelligence"
}

variable "environment" {
  type        = string
  description = "Deployment environment; disambiguates the log sink name, which is project-global."
}

variable "cloud_run_service_name" {
  type        = string
  description = "Cloud Run service whose stdout carries the compliance audit records."
}
