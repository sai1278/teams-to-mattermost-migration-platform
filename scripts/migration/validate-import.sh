#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../lib/common.sh"

show_help_if_requested "${1:-}" "bash ./scripts/migration/validate-import.sh [payload-jsonl]"

load_env_file
ensure_command docker
ensure_docker_running

PAYLOAD_PATH="${1:-${LOCAL_IMPORT_OUTPUT:-${DEFAULT_OUTPUT_JSONL}}}"
require_running_core_service mattermost

if [[ ! -f "${PAYLOAD_PATH}" ]]; then
  log_err "Import payload not found: ${PAYLOAD_PATH}"
  exit 1
fi

CONTAINER_ID="$(service_container_id mattermost)"
DEST_PATH="/tmp/import_data.jsonl"

log_info "Copying ${PAYLOAD_PATH} into the Mattermost container."
retry_command 3 2 docker cp "${PAYLOAD_PATH}" "${CONTAINER_ID}:${DEST_PATH}"
docker exec -u 0 "${CONTAINER_ID}" sh -c "chown 2000:2000 ${DEST_PATH} || true"

log_info "Running Mattermost bulk import validation."
retry_command 2 2 docker exec -i "${CONTAINER_ID}" mattermost import bulk "${DEST_PATH}" --validate
log_ok "Bulk import validation succeeded."
