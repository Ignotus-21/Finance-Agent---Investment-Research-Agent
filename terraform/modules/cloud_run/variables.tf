variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "environment" {
  type    = string
  default = "production"
}

variable "service_name" {
  type    = string
  default = "ira-multiagent-service"
}

variable "container_image" {
  type = string
}

variable "service_account_email" {
  type = string
}

variable "vpc_connector_id" {
  type = string
}

variable "min_instances" {
  type    = number
  default = 1
}

variable "max_instances" {
  type    = number
  default = 50
}

variable "container_concurrency" {
  type    = number
  default = 80
}

variable "offline_mode" {
  description = "Serve SEC data from the recorded corpus instead of sec.gov."
  type        = bool
  default     = false
}

variable "sec_edgar_user_agent" {
  description = "Contact string sent in the User-Agent header on every sec.gov request."
  type        = string
}

variable "custom_audiences" {
  description = "Audiences this service accepts on an incoming ID token, set on the service itself and mirrored into AUTH_ALLOWED_AUDIENCES so IAM and the application agree. Stable names, not the run.app URL: a caller has to mint a token for one of these, and the URL is not known until after the apply that creates it."
  type        = list(string)
  default     = []
}

variable "ingress" {
  description = "Cloud Run ingress setting."
  type        = string
  default     = "INGRESS_TRAFFIC_ALL"
}

variable "invoker_members" {
  description = "IAM principals granted roles/run.invoker on the service."
  type        = list(string)
  default     = []
}

variable "pubsub_topic_id" {
  type        = string
  description = "Topic the broadcaster publishes research.brief.completed events to."
}
