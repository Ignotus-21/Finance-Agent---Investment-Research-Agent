resource "google_cloud_run_v2_service" "ira_service" {
  name     = var.service_name
  location = var.region
  project  = var.project_id

  # Stated explicitly rather than inherited. The default is the same value, but
  # "the service is reachable from the internet" is a property that should be
  # written down next to the comment explaining why that is acceptable: the
  # authorization boundary here is IAM, and Cloud Build's smoke test probes the
  # tagged revision URL from outside the VPC.
  ingress = var.ingress

  # A second name the service will accept in the `aud` claim of an incoming ID
  # token, alongside its own run.app URL. The URL is the obvious choice and the
  # wrong one: it does not exist until this resource has been created, so using
  # it as the audience forces a two-phase apply, and referring to it from inside
  # the resource that defines it is a dependency cycle. A stable string chosen
  # up front has neither problem, and callers can be configured before the
  # service exists.
  custom_audiences = var.custom_audiences

  template {
    service_account = var.service_account_email

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    vpc_access {
      connector = var.vpc_connector_id
      egress    = "ALL_TRAFFIC"
    }

    containers {
      image = var.container_image

      resources {
        limits = {
          cpu    = "2"
          memory = "4Gi"
        }
        cpu_idle = false
      }

      # Was hard-coded to "production", which meant a staging deployment would
      # have labelled its own audit records as production.
      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }

      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }

      env {
        name  = "GCP_REGION"
        value = var.region
      }

      env {
        name  = "COORDINATOR_MODEL"
        value = "gemini-2.5-pro"
      }

      env {
        name  = "EXTRACTION_MODEL"
        value = "gemini-2.5-flash"
      }

      # The application defaults OFFLINE_MODE to true so that tests, CI and the
      # evaluation gate stay hermetic. A revision that inherits that default
      # serves the recorded FY2024 corpus and stamps it OFFLINE_FIXTURE: the
      # arithmetic is right, the freshness is a year stale, and the HTTP
      # response looks identical to a live one unless you read provenance.
      # Production has to opt in to live data, and this is where it does.
      env {
        name  = "OFFLINE_MODE"
        value = tostring(var.offline_mode)
      }

      # The same list the service itself accepts, handed to the application so
      # the two layers cannot drift. Cloud Run forwards the Authorization header
      # it authenticated with, so a token IAM allowed through arrives here
      # unchanged; if this were a subset of custom_audiences the application
      # would reject requests Cloud Run had already admitted, which presents as
      # an intermittent 401 with a green IAM policy and is thoroughly
      # unpleasant to diagnose. Empty in production makes the container refuse
      # to start.
      env {
        name  = "AUTH_ALLOWED_AUDIENCES"
        value = join(",", var.custom_audiences)
      }

      # Not a credential, and deliberately not in Secret Manager: this string is
      # transmitted in cleartext in the header of every single sec.gov request.
      # Keeping it as a plain env var means it is visible on the revision, which
      # is exactly where an operator looks when sec.gov starts answering 403.
      env {
        name  = "SEC_EDGAR_USER_AGENT"
        value = var.sec_edgar_user_agent
      }

      # The topic is environment-suffixed but the application's default is not,
      # so an unset value here means staging publishes into a topic that does
      # not exist - and the broadcaster, which must never fail a brief, would
      # swallow that as a logged warning nobody reads.
      env {
        name  = "PUBSUB_TOPIC_ID"
        value = var.pubsub_topic_id
      }

      # Mounts the ADK developer UI and agent REST surface at /adk. Off by
      # default in the application; a deployment has to ask for it, because
      # that surface takes free-text prompts straight to the model and so
      # bypasses the /v1 guardrail chain.
      env {
        name  = "ENABLE_ADK_WEB"
        value = tostring(var.enable_adk_web)
      }

      # How google-genai decides which backend to call. Unset, the SDK targets
      # the Gemini Developer API and looks for GOOGLE_API_KEY - which does not
      # exist here, on a revision whose service account already holds
      # roles/aiplatform.user. The failure is a 401 from a host nobody expected
      # the service to contact.
      env {
        name  = "GOOGLE_GENAI_USE_VERTEXAI"
        value = "TRUE"
      }

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }

      env {
        name  = "GOOGLE_CLOUD_LOCATION"
        value = var.region
      }

      startup_probe {
        http_get {
          path = "/healthz"
          port = 8080
        }
        initial_delay_seconds = 5
        period_seconds        = 10
        failure_threshold     = 3
      }

      liveness_probe {
        http_get {
          path = "/healthz"
          port = 8080
        }
        period_seconds    = 15
        failure_threshold = 3
      }
    }

    max_instance_request_concurrency = var.container_concurrency
    timeout                          = "120s"
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  # Cloud Build stages a green revision with --no-traffic, smoke-tests it on its
  # tagged URL, and only then shifts traffic by tag. Terraform's recorded view of
  # `traffic` is LATEST=100, so the next `apply` - for a change as unrelated as
  # an alert threshold - would quietly undo that cutover and re-point production
  # at whichever revision Terraform last created. Traffic belongs to the
  # pipeline; Terraform owns the service, not which revision is serving.
  lifecycle {
    ignore_changes = [traffic]
  }
}

# Explicit invoker bindings, empty by default.
#
# There is no allUsers or allAuthenticatedUsers binding anywhere in this config
# and that omission is load-bearing. The in-process check in
# src/api/dependencies.py accepts any bearer string of five characters or more,
# so Cloud Run IAM is the only real authentication boundary in front of this
# service. Adding allUsers here would remove it.
resource "google_cloud_run_v2_service_iam_member" "invokers" {
  for_each = toset(var.invoker_members)

  project  = google_cloud_run_v2_service.ira_service.project
  location = google_cloud_run_v2_service.ira_service.location
  name     = google_cloud_run_v2_service.ira_service.name
  role     = "roles/run.invoker"
  member   = each.value
}
