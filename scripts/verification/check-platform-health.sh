#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../lib/common.sh"

show_help_if_requested "${1:-}" "bash ./scripts/verification/check-platform-health.sh"

load_env_file
ensure_command docker
ensure_command curl

log_info "Running platform health checks."

ensure_docker_running
log_ok "Docker daemon is reachable."

require_running_core_service postgres
require_running_core_service mattermost

wait_for_service_health postgres 30
wait_for_service_health mattermost 30
wait_for_http "${MM_SERVICESETTINGS_SITEURL}/api/v4/system/ping" 30

log_ok "Platform health checks passed."
