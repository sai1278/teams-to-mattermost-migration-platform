#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../lib/common.sh"

show_help_if_requested "${1:-}" "bash ./scripts/monitoring/stop-monitoring.sh"

load_env_file
ensure_command docker
ensure_docker_running

log_info "Stopping the local observability stack."
compose_monitoring down --remove-orphans
log_ok "Monitoring services stopped."
