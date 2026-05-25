#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../lib/common.sh"

show_help_if_requested "${1:-}" "bash ./scripts/migration/transform-export.sh [input-json] [output-jsonl]"

load_env_file
ensure_command python3

INPUT_PATH="${1:-${LOCAL_IMPORT_INPUT:-${DEFAULT_INPUT_EXPORT}}}"
OUTPUT_PATH="${2:-${LOCAL_IMPORT_OUTPUT:-${DEFAULT_OUTPUT_JSONL}}}"
ANONYMIZE_FLAG="${ANONYMIZE_EXPORTS:-false}"
METRICS_OUTPUT_PATH="${TMMP_METRICS_OUTPUT_PATH:-${DEFAULT_METRICS_OUTPUT}}"

mkdir -p "$(dirname "${OUTPUT_PATH}")"
mkdir -p "$(dirname "${METRICS_OUTPUT_PATH}")"

log_info "Transforming Teams export input into Mattermost JSONL."

parser_args=(
  --input "${INPUT_PATH}"
  --output "${OUTPUT_PATH}"
  --metrics-output "${METRICS_OUTPUT_PATH}"
)

if [[ "${ANONYMIZE_FLAG}" == "true" ]]; then
  parser_args+=(--anonymize)
fi

PYTHONPATH="${PROJECT_ROOT}/apps/parser/src" python3 -m teams_mattermost_migration_parser.cli "${parser_args[@]}"

log_ok "Generated import payload at ${OUTPUT_PATH}."
