#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../lib/common.sh"

show_help_if_requested "${1:-}" "bash ./scripts/bootstrap/bootstrap-workspace.sh"

log_info "Preparing the local workspace for platform development."

ensure_command docker
ensure_command python3
ensure_command curl
ensure_docker_running

copy_env_template_if_missing
mkdir -p "${PROJECT_ROOT}/artifacts/imports"
mkdir -p "${PROJECT_ROOT}/artifacts/metrics"

log_ok "Workspace bootstrap complete."
log_info "Next steps:"
log_info "  1. Review ${ENV_FILE}"
log_info "  2. Run make up"
log_info "  3. Run make transform"
