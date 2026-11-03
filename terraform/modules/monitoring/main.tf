resource "google_monitoring_dashboard" "ira_observability" {
  project        = var.project_id
  dashboard_json = file(var.dashboard_json_path)
}

resource "google_monitoring_notification_channel" "oncall_email" {
  project      = var.project_id
  display_name = "IRA On-Call (${var.environment})"
  type         = "email"

  labels = {
    email_address = var.oncall_email
  }
}

resource "google_monitoring_custom_service" "ira" {
  project      = var.project_id
  service_id   = "ira-multiagent-${var.environment}"
  display_name = "IRA Multi-Agent Research Service (${var.environment})"
}

locals {
  cloud_run_filter = "resource.type=\"cloud_run_revision\" resource.labels.service_name=\"${var.cloud_run_service_name}\""
}

resource "google_monitoring_slo" "availability" {
  project      = var.project_id
  service      = google_monitoring_custom_service.ira.service_id
  slo_id       = "ira-availability-slo"
  display_name = "Availability >= 99.9% (30d rolling)"

  goal                = 0.999
  rolling_period_days = 30

  request_based_sli {
    good_total_ratio {
      good_service_filter  = "${local.cloud_run_filter} metric.type=\"run.googleapis.com/request_count\" metric.labels.response_code_class!=\"5xx\""
      total_service_filter = "${local.cloud_run_filter} metric.type=\"run.googleapis.com/request_count\""
    }
  }
}

resource "google_monitoring_slo" "latency_p95" {
  project      = var.project_id
  service      = google_monitoring_custom_service.ira.service_id
  slo_id       = "ira-latency-p95-slo"
  display_name = "95% of requests complete within 60s (30d rolling)"

  goal                = 0.95
  rolling_period_days = 30

  request_based_sli {
    distribution_cut {
      distribution_filter = "${local.cloud_run_filter} metric.type=\"run.googleapis.com/request_latencies\""
      range {
        max = 60000 # milliseconds
      }
    }
  }
}

resource "google_monitoring_slo" "error_rate" {
  project      = var.project_id
  service      = google_monitoring_custom_service.ira.service_id
  slo_id       = "ira-error-rate-slo"
  display_name = "Successful (2xx) response rate >= 98% (30d rolling)"

  goal                = 0.98
  rolling_period_days = 30

  request_based_sli {
    good_total_ratio {
      good_service_filter  = "${local.cloud_run_filter} metric.type=\"run.googleapis.com/request_count\" metric.labels.response_code_class=\"2xx\""
      total_service_filter = "${local.cloud_run_filter} metric.type=\"run.googleapis.com/request_count\""
    }
  }
}

# ---------------------------------------------------------------------------
# Log-based metrics backing the guardrail-spike and SEC-429 alert policies.
# ---------------------------------------------------------------------------
resource "google_logging_metric" "guardrail_rejections" {
  project = var.project_id
  name    = "ira/guardrail_rejections"
  filter  = <<-EOT
    resource.type                                     = "cloud_run_revision"
    resource.labels.service_name                      = "${var.cloud_run_service_name}"
    jsonPayload.compliance_metadata.guardrail_verdict =~ "REJECT_.*"
  EOT

  description = "Count of requests rejected by the pre-execution guardrail classifier."

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }
}

resource "google_logging_metric" "sec_upstream_rate_limit" {
  project = var.project_id
  name    = "ira/sec_upstream_429"
  filter  = <<-EOT
    resource.type                = "cloud_run_revision"
    resource.labels.service_name = "${var.cloud_run_service_name}"
    jsonPayload.message          =~ "UPSTREAM_RATE_LIMIT|429"
  EOT

  description = "Count of SEC EDGAR upstream rate-limit responses."

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }
}

# ---------------------------------------------------------------------------
# Alert policies.
# ---------------------------------------------------------------------------

resource "google_monitoring_alert_policy" "availability_fast_burn" {
  project      = var.project_id
  display_name = "IRA Availability SLO - fast burn (10x over 1h)"
  combiner     = "OR"

  conditions {
    display_name = "Error budget burning 10x faster than sustainable"
    condition_threshold {
      filter          = "select_slo_burn_rate(\"${google_monitoring_slo.availability.id}\", \"3600s\")"
      comparison      = "COMPARISON_GT"
      threshold_value = 10
      duration        = "0s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_MEAN"
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.oncall_email.id]

  documentation {
    content   = "Availability error budget is burning 10x too fast. Triage: docs/operational_runbook.md section 3. If a deploy just completed, roll back per section 4.3."
    mime_type = "text/markdown"
  }
}

resource "google_monitoring_alert_policy" "availability_slow_burn" {
  project      = var.project_id
  display_name = "IRA Availability SLO - slow burn (2x over 6h)"
  combiner     = "OR"

  conditions {
    display_name = "Error budget burning 2x faster than sustainable"
    condition_threshold {
      filter          = "select_slo_burn_rate(\"${google_monitoring_slo.availability.id}\", \"21600s\")"
      comparison      = "COMPARISON_GT"
      threshold_value = 2
      duration        = "1800s"

      aggregations {
        alignment_period   = "600s"
        per_series_aligner = "ALIGN_MEAN"
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.oncall_email.id]

  documentation {
    content   = "Sustained low-grade failure rate. Not an outage, but the 30-day error budget will be exhausted if this continues."
    mime_type = "text/markdown"
  }
}

resource "google_monitoring_alert_policy" "latency_regression" {
  project      = var.project_id
  display_name = "IRA P95 Latency > 60s (DoD threshold breach)"
  combiner     = "OR"

  conditions {
    display_name = "P95 request latency above the 60s DoD ceiling for 5 minutes"
    condition_threshold {
      filter          = "${local.cloud_run_filter} metric.type=\"run.googleapis.com/request_latencies\""
      comparison      = "COMPARISON_GT"
      threshold_value = 60000
      duration        = "300s"

      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_PERCENTILE_95"
        cross_series_reducer = "REDUCE_MAX"
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.oncall_email.id]

  documentation {
    content   = "P95 latency exceeded the 60s Definition of Done ceiling. Check Vertex AI regional health first (runbook 3.2), then context cache hit rate."
    mime_type = "text/markdown"
  }
}

# Mirrors the runbook's GuardrailBlockedRate > 10% trigger.
resource "google_monitoring_alert_policy" "guardrail_spike" {
  project      = var.project_id
  display_name = "IRA Adversarial Injection Spike"
  combiner     = "OR"

  conditions {
    display_name = "Guardrail rejections exceed 10/min for 5 minutes"
    condition_threshold {
      filter          = "resource.type=\"cloud_run_revision\" metric.type=\"logging.googleapis.com/user/${google_logging_metric.guardrail_rejections.name}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 10
      duration        = "300s"

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_DELTA"
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.oncall_email.id]

  documentation {
    content   = "Sustained adversarial prompt activity. Follow runbook 3.3 to extract offending principals and apply a Cloud Armor deny rule."
    mime_type = "text/markdown"
  }
}

# Mirrors the runbook's SEC_429_SPIKE trigger.
resource "google_monitoring_alert_policy" "sec_rate_limit_spike" {
  project      = var.project_id
  display_name = "IRA SEC EDGAR Upstream 429 Spike"
  combiner     = "OR"

  conditions {
    display_name = "SEC upstream returning 429 more than 5 times per minute"
    condition_threshold {
      filter          = "resource.type=\"cloud_run_revision\" metric.type=\"logging.googleapis.com/user/${google_logging_metric.sec_upstream_rate_limit.name}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 5
      duration        = "180s"

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_DELTA"
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.oncall_email.id]

  documentation {
    content   = "Token bucket is over-driving SEC EDGAR. Follow runbook 3.1: reduce SEC_RATE_LIMIT_PER_SEC and confirm the circuit breaker is serving cached fallbacks."
    mime_type = "text/markdown"
  }
}
