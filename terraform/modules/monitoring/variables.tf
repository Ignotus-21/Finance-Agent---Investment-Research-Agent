variable "project_id" {
  description = "The Google Cloud Project ID"
  type        = string
}

variable "environment" {
  description = "Deployment environment; disambiguates SLO and channel names"
  type        = string
}

variable "cloud_run_service_name" {
  description = "Cloud Run service name that every SLI filters on"
  type        = string
}

variable "dashboard_json_path" {
  description = "Path to the dashboard definition. Kept as a file rather than inline HCL so it can be edited and previewed in the Cloud Console UI."
  type        = string
}

variable "oncall_email" {
  description = "Destination for alert notifications"
  type        = string
}
