#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# One-time adoption of resources that pre-date Terraform management.
# Idempotent: addresses already present in state are skipped.
#
#   PROJECT_ID=adis-workshop REGION=us-central1 ENVIRONMENT=test \
#     scripts/infra_import_existing.sh
# ---------------------------------------------------------------------------
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-us-central1}"
ENVIRONMENT="${ENVIRONMENT:?set ENVIRONMENT}"
INFRA="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/infra.sh"

"${INFRA}" init
STATE="$("${INFRA}" state list 2>/dev/null || true)"

adopt() {
  local addr="$1" id="$2"
  if grep -Fxq "${addr}" <<<"${STATE}"; then
    echo "skip   ${addr}"
  else
    echo "import ${addr}"
    "${INFRA}" import "${addr}" "${id}"
  fi
}

adopt 'module.iam.google_service_account.ira_runtime_sa' \
  "projects/${PROJECT_ID}/serviceAccounts/ira-runtime-${ENVIRONMENT}-sa@${PROJECT_ID}.iam.gserviceaccount.com"
adopt 'module.iam.google_service_account.ira_caller_sa' \
  "projects/${PROJECT_ID}/serviceAccounts/ira-caller-${ENVIRONMENT}-sa@${PROJECT_ID}.iam.gserviceaccount.com"
adopt 'module.bigquery.google_bigquery_dataset.ira_dataset' \
  "projects/${PROJECT_ID}/datasets/ira_financial_intelligence_${ENVIRONMENT}"
adopt 'google_pubsub_topic.research_events' \
  "projects/${PROJECT_ID}/topics/ira-research-events-${ENVIRONMENT}"
adopt 'module.cloud_run.google_cloud_run_v2_service.ira_service' \
  "projects/${PROJECT_ID}/locations/${REGION}/services/ira-service-${ENVIRONMENT}"
adopt 'google_cloud_run_v2_service.ira_ui[0]' \
  "projects/${PROJECT_ID}/locations/${REGION}/services/ira-ui-${ENVIRONMENT}"
