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

if [[ -f "${OUTPUT_PATH}" ]]; then
  chmod 600 "${OUTPUT_PATH}"
fi
# Also chmod any chunk part files
base_dir="$(dirname "${OUTPUT_PATH}")"
base_name="$(basename "${OUTPUT_PATH}")"
stem="${base_name%.*}"
ext="${base_name##*.}"
# Find and chmod all matching parts: e.g. import.part*.jsonl
for part_file in "${base_dir}/${stem}.part"*".${ext}"; do
  if [[ -f "${part_file}" ]]; then
    chmod 600 "${part_file}"
  fi
done

log_ok "Generated import payload at ${OUTPUT_PATH}."
