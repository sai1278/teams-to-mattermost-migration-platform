#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../lib/common.sh"

show_help_if_requested "${1:-}" "bash ./scripts/verification/verify-migration-state.sh"

load_env_file
ensure_command docker
ensure_docker_running

require_running_core_service postgres

run_sql() {
  compose_core exec -T postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -tAc "$1"
}

log_info "Collecting migration verification data from PostgreSQL."

QUERY_START_TIME="$(date +%s)"
TEAM_COUNT="$(run_sql 'SELECT COUNT(*) FROM teams;')"
CHANNEL_COUNT="$(run_sql 'SELECT COUNT(*) FROM channels;')"
USER_COUNT="$(run_sql 'SELECT COUNT(*) FROM users;')"
POST_COUNT="$(run_sql 'SELECT COUNT(*) FROM posts;')"
QUERY_DURATION="$(( $(date +%s) - QUERY_START_TIME ))"

log_info "teams=${TEAM_COUNT} channels=${CHANNEL_COUNT} users=${USER_COUNT} posts=${POST_COUNT} query_duration_seconds=${QUERY_DURATION}"

if [[ "${TEAM_COUNT}" == "0" || "${USER_COUNT}" == "0" || "${POST_COUNT}" == "0" ]]; then
  log_err "Verification failed because one or more critical tables are empty."
  exit 1
fi

log_ok "Migration state looks healthy."
