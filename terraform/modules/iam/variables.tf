variable "project_id" {
  type = string
}

variable "service_account_name" {
  type    = string
  default = "ira-runtime-sa"
}

variable "caller_service_account_name" {
  type    = string
  default = "ira-caller-sa"
}

variable "token_creator_members" {
  description = "Principals allowed to impersonate the caller service account."
  type        = list(string)
  default     = []
}
