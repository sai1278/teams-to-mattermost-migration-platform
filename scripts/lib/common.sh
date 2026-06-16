#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${PROJECT_ROOT}/.env"
ENV_TEMPLATE="${PROJECT_ROOT}/infrastructure/docker/.env.example"
COMPOSE_FILE_CORE="${PROJECT_ROOT}/infrastructure/docker/docker-compose.yml"
COMPOSE_FILE_MONITORING="${PROJECT_ROOT}/infrastructure/docker/docker-compose.monitoring.yml"
# shellcheck disable=SC2034
DEFAULT_INPUT_EXPORT="${PROJECT_ROOT}/tests/fixtures/sample-teams-export.json"
# shellcheck disable=SC2034
DEFAULT_OUTPUT_JSONL="${PROJECT_ROOT}/artifacts/imports/sample-import.jsonl"
# shellcheck disable=SC2034
DEFAULT_METRICS_OUTPUT="${PROJECT_ROOT}/artifacts/metrics/parser.prom"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
  echo -e "${BLUE}[INFO] $(date '+%Y-%m-%d %H:%M:%S') - $1${NC}"
}

log_ok() {
  echo -e "${GREEN}[OK] $(date '+%Y-%m-%d %H:%M:%S') - $1${NC}"
}

log_warn() {
  echo -e "${YELLOW}[WARN] $(date '+%Y-%m-%d %H:%M:%S') - $1${NC}"
}

log_err() {
  echo -e "${RED}[FAIL] $(date '+%Y-%m-%d %H:%M:%S') - $1${NC}" >&2
}

ensure_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    log_err "Required command not found: $1"
    exit 1
  fi
}

ensure_docker_running() {
  if ! docker info >/dev/null 2>&1; then
    log_err "Docker is not reachable. Start Docker Desktop or Docker Engine first."
    exit 1
  fi
}

retry_command() {
  local attempts="$1"
  local delay_seconds="$2"
  shift 2

  local attempt=1
  until "$@"; do
    if (( attempt >= attempts )); then
      return 1
    fi
    sleep "${delay_seconds}"
    attempt=$(( attempt + 1 ))
  done
}

copy_env_template_if_missing() {
  if [[ ! -f "${ENV_FILE}" ]]; then
    cp "${ENV_TEMPLATE}" "${ENV_FILE}"
    log_warn "Created ${ENV_FILE} from ${ENV_TEMPLATE}. Review credentials before continuing."
  fi
}

load_env_file() {
  copy_env_template_if_missing
  # shellcheck disable=SC1090
  set -a
  source "${ENV_FILE}"
  set +a
}

print_usage() {
  cat <<EOF
Usage: $1
EOF
}

show_help_if_requested() {
  if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    print_usage "$2"
    exit 0
  fi
}

compose_core() {
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE_CORE}" "$@"
}

compose_monitoring() {
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE_MONITORING}" "$@"
}

service_container_id() {
  compose_core ps -q "$1"
}

monitoring_service_container_id() {
  compose_monitoring ps -q "$1"
}

wait_for_service_health() {
  local service_name="$1"
  local timeout_seconds="${2:-180}"
  local start_time
  local container_id
  local current_status

  start_time="$(date +%s)"
  container_id="$(service_container_id "${service_name}")"

  if [[ -z "${container_id}" ]]; then
    log_err "Could not locate a running container for service '${service_name}'."
    exit 1
  fi

  while true; do
    current_status="$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${container_id}")"
    if [[ "${current_status}" == "healthy" || "${current_status}" == "running" ]]; then
      log_ok "Service '${service_name}' is ${current_status}."
      return 0
    fi

    if (( "$(date +%s)" - start_time >= timeout_seconds )); then
      log_err "Timed out waiting for '${service_name}' to become healthy. Last status: ${current_status}"
      exit 1
    fi

    sleep 3
  done
}

wait_for_http() {
  local url="$1"
  local timeout_seconds="${2:-180}"
  local start_time
  local status_code

  start_time="$(date +%s)"
  while true; do
    status_code="$(curl -sS -o /dev/null -w '%{http_code}' "${url}" || true)"
    if [[ "${status_code}" == "200" ]]; then
      log_ok "HTTP endpoint is ready: ${url}"
      return 0
    fi

    if (( "$(date +%s)" - start_time >= timeout_seconds )); then
      log_err "Timed out waiting for HTTP 200 from ${url}. Last code: ${status_code:-n/a}"
      exit 1
    fi

    sleep 3
  done
}

require_running_core_service() {
  local service_name="$1"
  local container_id

  container_id="$(service_container_id "${service_name}")"
  if [[ -z "${container_id}" ]]; then
    log_err "Core service '${service_name}' is not running. Start the platform first."
    exit 1
  fi
}

confirm_action() {
  local prompt="$1"
  local default_answer="${2:-N}"
  local reply

  read -r -p "${prompt} " reply
  reply="${reply:-${default_answer}}"
  if [[ ! "${reply}" =~ ^[Yy]$ ]]; then
    log_warn "Operation cancelled."
    exit 0
  fi
}
