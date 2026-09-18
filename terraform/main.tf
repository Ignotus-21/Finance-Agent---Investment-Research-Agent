terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.38.0"
    }
  }

  # Remote state. Local state means the only record of what is deployed lives
  # on one laptop, with no locking: two concurrent applies interleave and the
  # loser's resources become orphans that nothing tracks.
  #
  # This is a *partial* configuration on purpose. A backend block cannot
  # interpolate variables, and the state bucket is per-project, so hard-coding
  # one project's bucket here would make the config unusable anywhere else.
  # Supply it at init time:
  #
  #   terraform init -backend-config=backend.hcl -migrate-state
  #
  # See backend.hcl.example. Chicken-and-egg: the bucket has to be created by
  # hand first, because the config that stores its state there cannot also be
  # the config that creates it.
  backend "gcs" {}
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# 0. Project API enablement.
# Every service listed is a hard dependency of some resource below. Declaring
# them here is what makes a brand-new project deployable without the manual
# `gcloud services enable` the runbook previously had to open with.
#
# `disable_on_destroy = false` is deliberate: a `terraform destroy` that turned
# off, say, logging.googleapis.com would break every other workload in the
# project that happens to share it. Enabling an API is additive; disabling one
# is not.
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
  source               = "./modules/iam"
  project_id           = var.project_id
  service_account_name = "ira-runtime-${var.environment}-sa"

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
  source     = "./modules/bigquery"
  project_id = var.project_id
  region     = var.region
  dataset_id = "ira_financial_intelligence_${var.environment}"

  depends_on = [google_project_service.required]
}

# 5. Production Cloud Run Service Module
module "cloud_run" {
  source                = "./modules/cloud_run"
  project_id            = var.project_id
  region                = var.region
  environment           = var.environment
  service_name          = "ira-service-${var.environment}"
  container_image       = var.container_image
  service_account_email = module.iam.service_account_email
  vpc_connector_id      = module.vpc.connector_id
  min_instances         = var.min_instances
  max_instances         = var.max_instances
  container_concurrency = var.container_concurrency

  # Runtime configuration. The application's own defaults are tuned for
  # hermetic tests, not for production; leaving them unset here is what made
  # the deployed service answer from recorded fixtures.
  offline_mode         = var.offline_mode
  sec_edgar_user_agent = var.sec_edgar_user_agent
  ingress              = var.ingress
  invoker_members      = var.invoker_members

  depends_on = [google_project_service.required]
}

# 6. Artifact Registry Module
# cloudbuild.yaml pushes here on every build. Declaring it in Terraform is what
# makes a fresh project deployable without a manual `gcloud artifacts repositories create`.
module "artifact_registry" {
  source        = "./modules/artifact_registry"
  project_id    = var.project_id
  region        = var.region
  environment   = var.environment
  repository_id = var.artifact_repository_id

  # Reuses the CMEK key from the secret_manager module instead of creating a
  # second key ring - one rotation schedule, one revocation point.
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

  # The dashboard definition lives outside terraform/ so it can be edited and
  # previewed in the Cloud Console before being committed.
  dashboard_json_path = "${path.root}/../configs/monitoring/cloud_monitoring_dashboard.json"

  depends_on = [google_project_service.required]
}

# 9. Continuous delivery trigger.
# cloudbuild.yaml is a complete pipeline that nothing invoked: every deploy was
# a hand-typed `gcloud builds submit`. This is the thing that fires it on merge.
#
# Count-gated because the GitHub connection it binds to is an OAuth grant, and
# an OAuth grant cannot be created by Terraform. Install the Cloud Build GitHub
# App on the repository once, then set enable_cloudbuild_trigger = true. That
# single manual step is recorded as a deviation rather than hidden.
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

  # Sourced from the module output rather than retyped. The previous hard-coded
  # `ira-multiagent-service` substitution did not match the Terraform service
  # name, so the pipeline and the IaC deployed two different Cloud Run services.
  substitutions = {
    _REGION        = var.region
    _ARTIFACT_REPO = var.artifact_repository_id
    _SERVICE_NAME  = module.cloud_run.service_name
  }

  depends_on = [google_project_service.required]
}
