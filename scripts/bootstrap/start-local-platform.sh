#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../lib/common.sh"

show_help_if_requested "${1:-}" "bash ./scripts/bootstrap/start-local-platform.sh"

load_env_file
ensure_command docker
ensure_command curl
ensure_docker_running

log_info "Starting the local Mattermost migration platform."
mkdir -p "${PROJECT_ROOT}/artifacts/imports"
mkdir -p "${PROJECT_ROOT}/artifacts/metrics"

compose_core up -d --remove-orphans

wait_for_service_health postgres 180
wait_for_service_health mattermost 240
wait_for_http "${MM_SERVICESETTINGS_SITEURL}/api/v4/system/ping" 240

log_ok "Local platform is ready."
