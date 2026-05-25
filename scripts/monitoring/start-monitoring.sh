#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../lib/common.sh"

show_help_if_requested "${1:-}" "bash ./scripts/monitoring/start-monitoring.sh"

load_env_file
ensure_command docker
ensure_docker_running

require_running_core_service mattermost

log_info "Starting the local observability stack."
compose_monitoring up -d --remove-orphans
log_ok "Monitoring services started."
