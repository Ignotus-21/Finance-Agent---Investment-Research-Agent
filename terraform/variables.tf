variable "project_id" {
  description = "The Google Cloud Project ID"
  type        = string
  default     = "ira-capstone-finance-prod"
}

variable "region" {
  description = "The target Google Cloud region"
  type        = string
  default     = "us-central1"
}

variable "environment" {
  description = "Deployment environment (development, staging, production)"
  type        = string
  default     = "production"
}

variable "container_image" {
  description = "Artifact Registry container image URI for the IRA service"
  type        = string
  default     = "us-central1-docker.pkg.dev/ira-capstone-finance-prod/ira-repo/ira-service:v1.0.0"
}

variable "min_instances" {
  description = "Minimum Cloud Run container instances"
  type        = number
  default     = 1
}

variable "max_instances" {
  description = "Maximum Cloud Run container instances for autoscaling"
  type        = number
  default     = 50
}

variable "container_concurrency" {
  description = "Concurrent requests per container instance"
  type        = number
  default     = 80
}
