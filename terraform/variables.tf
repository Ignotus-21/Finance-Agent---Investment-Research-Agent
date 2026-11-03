variable "project_id" {
  description = "Google Cloud project ID."
  type        = string
  default     = "ira-capstone-finance-prod"
}

variable "region" {
  description = "Google Cloud region for all regional resources."
  type        = string
  default     = "us-central1"
}

variable "environment" {
  description = "Environment suffix applied to every resource name (e.g. test, staging, production)."
  type        = string
  default     = "production"
}

variable "app_environment" {
  description = "Container ENVIRONMENT value (development, staging, production). Defaults to var.environment; set to \"production\" to enable the application's production startup guards regardless of resource naming."
  type        = string
  default     = ""
}

variable "container_image" {
  description = "Artifact Registry image URI for the research service."
  type        = string
  default     = "us-central1-docker.pkg.dev/ira-capstone-finance-prod/ira-repo/ira-agent:v1.0.0"
}

variable "min_instances" {
  description = "Minimum warm Cloud Run instances for the research service (0 pauses the always-on charge)."
  type        = number
  default     = 1
}

variable "max_instances" {
  description = "Maximum Cloud Run instances for the research service."
  type        = number
  default     = 50
}

variable "container_concurrency" {
  description = "Concurrent requests per container instance."
  type        = number
  default     = 80
}

variable "request_timeout" {
  description = "Maximum request duration for the research service (e.g. \"300s\"), sized for multi-turn ADK Server-Sent Events sessions."
  type        = string
  default     = "300s"
}

variable "artifact_repository_id" {
  description = "Artifact Registry repository ID; must match the _ARTIFACT_REPO substitution in cloudbuild.yaml."
  type        = string
  default     = "ira-repo"
}

variable "oncall_email" {
  description = "Email address receiving Cloud Monitoring alert notifications."
  type        = string
  default     = "ira-oncall@example.com"
}

variable "offline_mode" {
  description = "Serve the recorded FY2024 SEC corpus instead of live sec.gov when true."
  type        = bool
  default     = false
}

variable "sec_edgar_user_agent" {
  description = "SEC EDGAR User-Agent contact string (e.g. 'IRA Research admin@example.com'). Required: the service refuses to start in live mode without a valid contact."
  type        = string
}

variable "custom_audiences" {
  description = "Audiences accepted in the aud claim of incoming Google-signed ID tokens, configured on Cloud Run and mirrored into AUTH_ALLOWED_AUDIENCES (e.g. [\"ira-service-production\"])."
  type        = list(string)
  default     = []
}

variable "token_creator_members" {
  description = "Principals granted roles/iam.serviceAccountTokenCreator on the caller service account (e.g. [\"user:analyst@example.com\"])."
  type        = list(string)
  default     = []
}

variable "ingress" {
  description = "Cloud Run ingress setting. IAM is the authorization boundary; INGRESS_TRAFFIC_ALL allows the Cloud Build smoke test to reach the green revision."
  type        = string
  default     = "INGRESS_TRAFFIC_ALL"
}

variable "invoker_members" {
  description = "Additional principals granted roles/run.invoker on the research service. The caller service account is always included; allUsers is never permitted."
  type        = list(string)
  default     = []
}

variable "enable_cloudbuild_trigger" {
  description = "Create the Cloud Build GitHub trigger for cloudbuild.yaml. Requires the Cloud Build GitHub App to be installed on the repository first."
  type        = bool
  default     = false
}

variable "github_owner" {
  description = "GitHub organisation or user owning the repository."
  type        = string
  default     = "delta-fde"
}

variable "github_repo" {
  description = "GitHub repository name."
  type        = string
  default     = "itsadi-finance-investment-research-agent"
}

variable "cloudbuild_trigger_branch" {
  description = "Regex of branches whose pushes trigger a deployment."
  type        = string
  default     = "^develop$"
}

variable "enable_ui_service" {
  description = "Deploy the Streamlit analyst console as a companion Cloud Run service."
  type        = bool
  default     = false
}

variable "ui_container_image" {
  description = "Image built from Dockerfile.ui; required when enable_ui_service is true."
  type        = string
  default     = ""
}

variable "ui_invoker_members" {
  description = "Principals granted roles/run.invoker on the console service (e.g. [\"user:analyst@example.com\"]). Access is via gcloud run services proxy; allUsers is never permitted."
  type        = list(string)
  default     = []
}

variable "enable_adk_web" {
  description = "Mount the ADK developer UI and REST surface under /adk on the research service."
  type        = bool
  default     = false
}
