resource "google_cloud_run_v2_service" "ira_service" {
  name     = var.service_name
  location = var.region
  project  = var.project_id

  ingress = var.ingress

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
        cpu_idle          = false
        startup_cpu_boost = true
      }

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

      env {
        name  = "OFFLINE_MODE"
        value = tostring(var.offline_mode)
      }

      env {
        name  = "AUTH_ALLOWED_AUDIENCES"
        value = join(",", var.custom_audiences)
      }

      env {
        name  = "SEC_EDGAR_USER_AGENT"
        value = var.sec_edgar_user_agent
      }

      env {
        name  = "PUBSUB_TOPIC_ID"
        value = var.pubsub_topic_id
      }

      env {
        name  = "ENABLE_ADK_WEB"
        value = tostring(var.enable_adk_web)
      }

      env {
        name  = "DLP_BACKEND"
        value = var.dlp_backend
      }

      env {
        name  = "ENABLE_LIVE_NEWS_GROUNDING"
        value = tostring(var.enable_live_news_grounding)
      }

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
        timeout_seconds       = 5
        failure_threshold     = 10
      }

      liveness_probe {
        http_get {
          path = "/healthz"
          port = 8080
        }
        period_seconds    = 15
        timeout_seconds   = 5
        failure_threshold = 3
      }
    }

    max_instance_request_concurrency = var.container_concurrency
    timeout                          = var.request_timeout
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  lifecycle {
    ignore_changes = [traffic]
  }
}

resource "google_cloud_run_v2_service_iam_member" "invokers" {
  for_each = toset(var.invoker_members)

  project  = google_cloud_run_v2_service.ira_service.project
  location = google_cloud_run_v2_service.ira_service.location
  name     = google_cloud_run_v2_service.ira_service.name
  role     = "roles/run.invoker"
  member   = each.value
}
