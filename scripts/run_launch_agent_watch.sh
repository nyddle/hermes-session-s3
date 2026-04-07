#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
ENV_FILE="${HERMES_ENV_FILE:-${HERMES_HOME}/.env}"
PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

export HERMES_HOME
cd "${REPO_ROOT}"
exec "${PYTHON_BIN}" -m hermes_session_s3.cli watch
