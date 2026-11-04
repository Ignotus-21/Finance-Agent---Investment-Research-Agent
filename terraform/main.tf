terraform {
  required_version = ">= 1.9.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.38.0"
    }
  }

  backend "gcs" {}
}

provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  cloud_run_service_name = "ira-service-${var.environment}"
}

resource "google_project_service" "required" {
  for_each = toset([
    "aiplatform.googleapis.com",       # Vertex AI Gemini inference
    "artifactregistry.googleapis.com", # Container image repository
    "bigquery.googleapis.com",         # Audit log and metrics sink
    "cloudbuild.googleapis.com",       # CI/CD pipeline
    "cloudkms.googleapis.com",         # CMEK for secrets, buckets, images
    "cloudtrace.googleapis.com",       # OpenTelemetry span export
    "compute.googleapis.com",          # VPC, subnet, router, Cloud NAT
    "dlp.googleapis.com",              # PII inspection and redaction
    "iam.googleapis.com",              # Runtime service account
    "logging.googleapis.com",          # Structured logs, log-based metrics
    "modelarmor.googleapis.com",       # Prompt injection and jailbreak screening
    "monitoring.googleapis.com",       # Dashboard, SLOs, alert policies
    "pubsub.googleapis.com",           # Research completion events
    "run.googleapis.com",              # The service itself
    "secretmanager.googleapis.com",    # Market data credential
    "storage.googleapis.com",          # Brief and eval artifact buckets
    "vpcaccess.googleapis.com",        # Serverless VPC connector
  ])

  project = var.project_id
  service = each.value

  disable_on_destroy = false
}

# 1. Dedicated VPC & Private Networking Module
module "vpc" {
  source       = "./modules/vpc"
  project_id   = var.project_id
  region       = var.region
  network_name = "ira-vpc-${var.environment}"

  depends_on = [google_project_service.required]
}

# 2. Least-Privilege IAM & Service Account Module
module "iam" {
  source                      = "./modules/iam"
  project_id                  = var.project_id
  service_account_name        = "ira-runtime-${var.environment}-sa"
  caller_service_account_name = "ira-caller-${var.environment}-sa"
  token_creator_members       = var.token_creator_members

  depends_on = [google_project_service.required]
}

# 3. Secret Manager & Cloud KMS Module
module "secret_manager" {
  source     = "./modules/secret_manager"
  project_id = var.project_id
  region     = var.region

  depends_on = [google_project_service.required]
}

# 4. BigQuery Datasets & Audit Logging Module
module "bigquery" {
  source      = "./modules/bigquery"
  project_id  = var.project_id
  region      = var.region
  environment = var.environment
  dataset_id  = "ira_financial_intelligence_${var.environment}"

  cloud_run_service_name = local.cloud_run_service_name

  depends_on = [google_project_service.required]
}

# 5. Production Cloud Run Service Module
module "cloud_run" {
  source                = "./modules/cloud_run"
  project_id            = var.project_id
  region                = var.region
  environment           = coalesce(var.app_environment, var.environment)
  service_name          = local.cloud_run_service_name
  container_image       = var.container_image
  service_account_email = module.iam.service_account_email
  vpc_connector_id      = module.vpc.connector_id
  min_instances         = var.min_instances
  max_instances         = var.max_instances
  container_concurrency = var.container_concurrency
  request_timeout       = var.request_timeout

  offline_mode               = var.offline_mode
  sec_edgar_user_agent       = var.sec_edgar_user_agent
  custom_audiences           = var.custom_audiences
  ingress                    = var.ingress
  pubsub_topic_id            = google_pubsub_topic.research_events.name
  enable_adk_web             = var.enable_adk_web
  dlp_backend                = var.dlp_backend
  enable_live_news_grounding = var.enable_live_news_grounding
  enable_model_armor         = var.enable_model_armor
  model_armor_template       = var.model_armor_template

  invoker_members = concat(
    var.invoker_members,
    ["serviceAccount:ira-caller-${var.environment}-sa@${var.project_id}.iam.gserviceaccount.com"],
  )

  depends_on = [google_project_service.required, module.iam]
}

module "artifact_registry" {
  source        = "./modules/artifact_registry"
  project_id    = var.project_id
  region        = var.region
  environment   = var.environment
  repository_id = var.artifact_repository_id

  kms_key_id = module.secret_manager.kms_key_id

  depends_on = [google_project_service.required]
}

# 7. Secure Cloud Storage Module (CMEK, private, lifecycle-managed)
module "storage" {
  source                        = "./modules/storage"
  project_id                    = var.project_id
  region                        = var.region
  environment                   = var.environment
  kms_key_id                    = module.secret_manager.kms_key_id
  runtime_service_account_email = module.iam.service_account_email

  depends_on = [google_project_service.required]
}

# 8. Cloud Monitoring Module - dashboard, SLOs, log-based metrics, alerts
module "monitoring" {
  source                 = "./modules/monitoring"
  project_id             = var.project_id
  environment            = var.environment
  cloud_run_service_name = module.cloud_run.service_name
  oncall_email           = var.oncall_email

  dashboard_json_path = "${path.root}/../configs/monitoring/cloud_monitoring_dashboard.json"

  depends_on = [google_project_service.required]
}

resource "google_pubsub_topic" "research_events" {
  name    = "ira-research-events-${var.environment}"
  project = var.project_id

  labels = {
    env      = var.environment
    workload = "financial-intelligence"
  }

  message_retention_duration = "86400s"

  depends_on = [google_project_service.required]
}

resource "google_pubsub_subscription" "research_events_default" {
  name    = "${google_pubsub_topic.research_events.name}-default"
  topic   = google_pubsub_topic.research_events.id
  project = var.project_id

  ack_deadline_seconds       = 20
  message_retention_duration = "86400s"

  expiration_policy {
    ttl = "" # never expire; an auto-deleted subscription drops events silently
  }
}

resource "google_pubsub_topic_iam_member" "runtime_publisher" {
  project = var.project_id
  topic   = google_pubsub_topic.research_events.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${module.iam.service_account_email}"
}

resource "google_cloud_run_v2_service" "ira_ui" {
  count = var.enable_ui_service ? 1 : 0

  name     = "ira-ui-${var.environment}"
  project  = var.project_id
  location = var.region

  ingress = var.ingress

  template {
    service_account = module.iam.caller_service_account_email

    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }
    max_instance_request_concurrency = 20

    containers {
      image = var.ui_container_image

      ports {
        container_port = 8080
      }

      env {
        name  = "IRA_SERVICE_URL"
        value = module.cloud_run.service_url
      }

      env {
        name  = "IRA_AUDIENCE"
        value = length(var.custom_audiences) > 0 ? var.custom_audiences[0] : ""
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
      }

      startup_probe {
        http_get {
          path = "/_stcore/health"
        }
        initial_delay_seconds = 10
        period_seconds        = 5
        failure_threshold     = 6
      }
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_cloud_run_v2_service_iam_member" "ira_ui_invokers" {
  for_each = var.enable_ui_service ? toset(var.ui_invoker_members) : toset([])

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.ira_ui[0].name
  role     = "roles/run.invoker"
  member   = each.value
}

resource "google_cloudbuild_trigger" "cd" {
  count = var.enable_cloudbuild_trigger ? 1 : 0

  name        = "ira-cd-${var.environment}"
  description = "Lint, test, eval gate, build, blue/green deploy on merge."
  project     = var.project_id
  location    = var.region
  filename    = "cloudbuild.yaml"

  github {
    owner = var.github_owner
    name  = var.github_repo

    push {
      branch = var.cloudbuild_trigger_branch
    }
  }

  substitutions = {
    _REGION        = var.region
    _ARTIFACT_REPO = var.artifact_repository_id
    _SERVICE_NAME  = module.cloud_run.service_name
  }

  depends_on = [google_project_service.required]
}
