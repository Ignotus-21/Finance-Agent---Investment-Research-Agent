variable "project_id" {
  type        = string
  description = "GCP Project ID"
}

variable "region" {
  type        = string
  description = "GCP Region"
}

variable "network_name" {
  type        = string
  default     = "ira-vpc-network"
  description = "VPC Network Name"
}

variable "subnet_cidr" {
  type        = string
  default     = "10.10.0.0/20"
  description = "Primary subnet CIDR"
}

variable "connector_cidr" {
  type        = string
  default     = "10.10.16.0/28"
  description = "Serverless VPC Access connector CIDR"
}
