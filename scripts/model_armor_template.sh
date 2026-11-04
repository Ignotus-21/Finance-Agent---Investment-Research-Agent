#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Model Armor template lifecycle for the IRA prompt guardrail.
#
#   scripts/model_armor_template.sh create|describe|delete [project] [region] [template_id]
#
# Defaults: project = gcloud core/project, region = us-central1,
# template_id = ira-prompt-guard-<ENVIRONMENT:-test>.
# The hashicorp/google provider pinned in terraform/ has no Model Armor
# resource, so the template is created here and referenced from
# terraform.tfvars (model_armor_template). `create` is idempotent.
# ---------------------------------------------------------------------------
set -euo pipefail

ACTION="${1:-}"
PROJECT="${2:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${3:-us-central1}"
TEMPLATE_ID="${4:-ira-prompt-guard-${ENVIRONMENT:-test}}"
RESOURCE="projects/${PROJECT}/locations/${REGION}/templates/${TEMPLATE_ID}"

usage() {
  sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit 1
}

[[ -n "${ACTION}" && -n "${PROJECT}" ]] || usage

ma() { gcloud model-armor templates "$@" --project="${PROJECT}" --location="${REGION}"; }

exists() { ma describe "${TEMPLATE_ID}" >/dev/null 2>&1; }

create() {
  gcloud services enable modelarmor.googleapis.com --project="${PROJECT}" >/dev/null
  if exists; then
    echo "exists: ${RESOURCE}"
    return
  fi
  # Prompt-injection/jailbreak and malicious-URI detection at medium confidence,
  # plus the four Responsible AI categories. Sensitive-data (SDP) filtering is
  # deliberately left to the dedicated Cloud DLP masking layer (DLP_BACKEND).
  ma create "${TEMPLATE_ID}" \
    --pi-and-jailbreak-filter-settings-enforcement=enabled \
    --pi-and-jailbreak-filter-settings-confidence-level=medium-and-above \
    --malicious-uri-filter-settings-enforcement=enabled \
    --rai-settings-filters='[{"filterType":"HATE_SPEECH","confidenceLevel":"MEDIUM_AND_ABOVE"},{"filterType":"HARASSMENT","confidenceLevel":"MEDIUM_AND_ABOVE"},{"filterType":"DANGEROUS","confidenceLevel":"MEDIUM_AND_ABOVE"},{"filterType":"SEXUALLY_EXPLICIT","confidenceLevel":"MEDIUM_AND_ABOVE"}]' \
    --template-metadata-log-sanitize-operations \
    --labels="app=ira,environment=${ENVIRONMENT:-test}" \
    --quiet >/dev/null
  echo "created: ${RESOURCE}"
}

case "${ACTION}" in
  create)   create ;;
  describe) ma describe "${TEMPLATE_ID}" ;;
  delete)   exists && ma delete "${TEMPLATE_ID}" --quiet && echo "deleted: ${RESOURCE}" || echo "absent: ${RESOURCE}" ;;
  *)        usage ;;
esac
