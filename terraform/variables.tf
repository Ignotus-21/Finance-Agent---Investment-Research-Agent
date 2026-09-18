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

variable "artifact_repository_id" {
  description = "Artifact Registry repository name. MUST match the _ARTIFACT_REPO substitution in cloudbuild.yaml, otherwise the pipeline pushes to a repository Terraform does not manage."
  type        = string
  default     = "ira-repo"
}

variable "oncall_email" {
  description = "Email address that receives Cloud Monitoring alert notifications"
  type        = string
  default     = "ira-oncall@example.com"
}

# --- Runtime configuration -------------------------------------------------
# The application defaults in src/config.py are chosen so that tests, CI and
# the evaluation gate are hermetic. Production needs the opposite defaults, and
# these variables are where that inversion happens.

variable "offline_mode" {
  description = "When true the service answers from the recorded FY2024 SEC corpus and never calls sec.gov. Defaults to false here because a production revision serving fixtures is indistinguishable from a live one unless you read the provenance field on every response."
  type        = bool
  default     = false
}

variable "sec_edgar_user_agent" {
  description = "Contact string sent in the User-Agent header on every sec.gov request, e.g. 'IRA Research admin@example.com'. Deliberately has no default: SEC throttles and then IP-bans callers it cannot identify, all egress leaves through one VPC connector, so the ban would land on the whole service. A wrong value here fails loudly at startup instead."
  type        = string
}

variable "custom_audiences" {
  description = "Audiences accepted in the `aud` claim of an incoming Google-signed ID token, configured on the Cloud Run service and mirrored into the container. Use a stable name such as 'ira-service-production'. Not the run.app URL: it does not exist until the apply that creates the service, so using it forces a two-phase apply, and a Google *user* account cannot mint a token for an arbitrary audience anyway - callers impersonate the caller service account to do that. A production container started with this empty exits rather than accept credentials it cannot verify."
  type        = list(string)
  default     = []
}

variable "token_creator_members" {
  description = "Principals granted roles/iam.serviceAccountTokenCreator on the caller service account, e.g. ['user:analyst@example.com']. That role is what lets a human run `gcloud auth print-identity-token --impersonate-service-account` and get a token the service will accept. Scoped to the caller SA specifically, which holds run.invoker and nothing else, so the grant cannot be used to reach Vertex AI, BigQuery or Secret Manager."
  type        = list(string)
  default     = []
}

variable "ingress" {
  description = "Cloud Run ingress setting. INGRESS_TRAFFIC_ALL because Cloud Build smoke-tests the tagged green revision from outside the VPC; the authorization boundary is IAM, not the network."
  type        = string
  default     = "INGRESS_TRAFFIC_ALL"
}

variable "invoker_members" {
  description = "IAM principals granted roles/run.invoker, e.g. ['user:analyst@example.com']. Empty by default; the caller service account is appended automatically. Never set this to allUsers or allAuthenticatedUsers - the application verifies the ID token's signature and audience, but an anonymous caller would never reach that code with a token to verify, so IAM remains the outer boundary."
  type        = list(string)
  default     = []
}

# --- Continuous delivery ---------------------------------------------------

variable "enable_cloudbuild_trigger" {
  description = "Create the Cloud Build trigger that runs cloudbuild.yaml on merge. Requires the Cloud Build GitHub App to be installed on the repository first - that is an OAuth grant and cannot be created by Terraform."
  type        = bool
  default     = false
}

variable "github_owner" {
  description = "GitHub organisation or user owning the repository"
  type        = string
  default     = "delta-fde"
}

variable "github_repo" {
  description = "GitHub repository name"
  type        = string
  default     = "itsadi-finance-investment-research-agent"
}

variable "cloudbuild_trigger_branch" {
  description = "Regex of branches whose merges trigger a deployment"
  type        = string
  default     = "^develop$"
}

variable "enable_ui_service" {
  type        = bool
  default     = false
  description = <<-EOT
    Deploy the Streamlit test console as a second Cloud Run service.

    Off by default. It is a testing surface: it renders the brief in a way that
    makes provenance and the offline/live data path obvious at a glance, which
    is exactly what you want while verifying a deployment and exactly what you
    do not want as a permanent, separately-versioned front end to a compliance
    system.
  EOT
}

variable "ui_container_image" {
  type        = string
  default     = ""
  description = "Image built from Dockerfile.ui. Required when enable_ui_service is true."
}

variable "ui_invoker_members" {
  type        = list(string)
  default     = []
  description = <<-EOT
    Principals allowed to open the console, as IAM members
    (e.g. "user:analyst@example.com").

    Empty by default, and no allUsers. The console holds an identity that can
    invoke the research API, so anyone who can reach the console can reach the
    API through it - making it public would hand that authority to the
    internet. Access is via `gcloud run services proxy`, which authenticates
    the tunnel.
  EOT
}

variable "enable_adk_web" {
  type        = bool
  default     = false
  description = "Mount the ADK developer UI at /adk on the research service. See the cloud_run module variable of the same name."
}
