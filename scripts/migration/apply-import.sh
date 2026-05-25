#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../lib/common.sh"

show_help_if_requested "${1:-}" "bash ./scripts/migration/apply-import.sh [payload-jsonl]"

load_env_file
ensure_command docker
ensure_docker_running

PAYLOAD_PATH="${1:-${LOCAL_IMPORT_OUTPUT:-${DEFAULT_OUTPUT_JSONL}}}"
AUTO_APPROVE="${AUTO_APPROVE_IMPORT:-false}"

bash "${SCRIPT_DIR}/validate-import.sh" "${PAYLOAD_PATH}"

if [[ "${AUTO_APPROVE}" != "true" ]]; then
  confirm_action "Apply the import payload to Mattermost? [y/N]" "N"
fi

CONTAINER_ID="$(service_container_id mattermost)"
DEST_PATH="/tmp/import_data.jsonl"

log_info "Applying Mattermost bulk import."
retry_command 2 2 docker exec -i "${CONTAINER_ID}" mattermost import bulk "${DEST_PATH}" --apply

bash "${SCRIPT_DIR}/../verification/verify-migration-state.sh"
log_ok "Bulk import apply completed."
