terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.38.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# 1. Dedicated VPC & Private Networking Module
module "vpc" {
  source       = "./modules/vpc"
  project_id   = var.project_id
  region       = var.region
  network_name = "ira-vpc-${var.environment}"
}

# 2. Least-Privilege IAM & Service Account Module
module "iam" {
  source               = "./modules/iam"
  project_id           = var.project_id
  service_account_name = "ira-runtime-${var.environment}-sa"
}

# 3. Secret Manager & Cloud KMS Module
module "secret_manager" {
  source     = "./modules/secret_manager"
  project_id = var.project_id
  region     = var.region
}

# 4. BigQuery Datasets & Audit Logging Module
module "bigquery" {
  source     = "./modules/bigquery"
  project_id = var.project_id
  region     = var.region
  dataset_id = "ira_financial_intelligence_${var.environment}"
}

# 5. Production Cloud Run Service Module
module "cloud_run" {
  source                = "./modules/cloud_run"
  project_id            = var.project_id
  region                = var.region
  service_name          = "ira-service-${var.environment}"
  container_image       = var.container_image
  service_account_email = module.iam.service_account_email
  vpc_connector_id      = module.vpc.connector_id
  min_instances         = var.min_instances
  max_instances         = var.max_instances
  container_concurrency = var.container_concurrency
}
