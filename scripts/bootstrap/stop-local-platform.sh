#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../lib/common.sh"

show_help_if_requested "${1:-}" "bash ./scripts/bootstrap/stop-local-platform.sh"

load_env_file
ensure_command docker
ensure_docker_running

log_info "Stopping the local Mattermost migration platform."
compose_core down --remove-orphans
log_ok "Core services stopped."
