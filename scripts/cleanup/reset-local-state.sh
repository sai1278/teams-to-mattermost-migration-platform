#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../lib/common.sh"

show_help_if_requested "${1:-}" "bash ./scripts/cleanup/reset-local-state.sh [--force]"

load_env_file
ensure_command docker
ensure_docker_running

FORCE_RESET="${1:-}"
if [[ "${FORCE_RESET}" != "--force" ]]; then
  confirm_action "This will remove local containers, networks, volumes, and generated payloads. Continue? [y/N]" "N"
fi

log_info "Stopping monitoring services."
compose_monitoring down --remove-orphans --volumes || true

log_info "Stopping core services and removing state."
compose_core down --remove-orphans --volumes

rm -rf "${PROJECT_ROOT}/artifacts/imports"
mkdir -p "${PROJECT_ROOT}/artifacts/imports"
rm -rf "${PROJECT_ROOT}/artifacts/metrics"
mkdir -p "${PROJECT_ROOT}/artifacts/metrics"

log_ok "Local environment reset complete."
