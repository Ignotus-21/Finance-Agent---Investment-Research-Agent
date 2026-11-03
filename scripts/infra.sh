#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# IRA infrastructure lifecycle wrapper around Terraform.
#
#   scripts/infra.sh init|validate|plan|apply|output|pause|resume|destroy|import <addr> <id>
#
# Requires terraform/backend.hcl and terraform/terraform.tfvars (both gitignored;
# see the *.example files). Override TERRAFORM_BIN to use a non-PATH binary.
# ---------------------------------------------------------------------------
set -euo pipefail

TF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../terraform" && pwd)"
TF_BIN="${TERRAFORM_BIN:-terraform}"
BACKEND_CONFIG="${BACKEND_CONFIG:-${TF_DIR}/backend.hcl}"
VAR_FILE="${VAR_FILE:-${TF_DIR}/terraform.tfvars}"

usage() {
  sed -n '2,9p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit 1
}

require_files() {
  [[ -f "${BACKEND_CONFIG}" ]] || { echo "missing ${BACKEND_CONFIG} (copy backend.hcl.example)"; exit 2; }
  [[ -f "${VAR_FILE}" ]] || { echo "missing ${VAR_FILE} (copy terraform.tfvars.example)"; exit 2; }
}

tf() { "${TF_BIN}" -chdir="${TF_DIR}" "$@"; }

init() {
  require_files
  tf init -input=false -reconfigure -backend-config="${BACKEND_CONFIG}" >/dev/null
}

apply() { tf apply -input=false -auto-approve -var-file="${VAR_FILE}" "$@"; }

case "${1:-}" in
  init)     init ;;
  validate) init; tf validate ;;
  plan)     init; tf plan -input=false -var-file="${VAR_FILE}" "${@:2}" ;;
  apply)    init; apply "${@:2}" ;;
  output)   init; tf output "${@:2}" ;;
  # pause: scale the research service to zero warm instances (stops the
  # always-on Cloud Run charge; connector and NAT keep billing).
  pause)    init; apply -var="min_instances=0" ;;
  resume)   init; apply ;;
  # destroy: kill switch. Removes every Terraform-managed resource. KMS key
  # rings cannot be deleted by Google Cloud and are only removed from state.
  destroy)  init; tf destroy -input=false -auto-approve -var-file="${VAR_FILE}" "${@:2}" ;;
  import)   [[ $# -eq 3 ]] || usage; init; tf import -input=false -var-file="${VAR_FILE}" "$2" "$3" ;;
  state)    init; tf state "${@:2}" ;;
  *)        usage ;;
esac
