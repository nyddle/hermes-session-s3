#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${REPO_ROOT}/.venv"
PYTHON_BIN="${VENV_DIR}/bin/python"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
RUNNER_SCRIPT="${REPO_ROOT}/scripts/run_launch_agent_watch.sh"
PLIST_TEMPLATE="${REPO_ROOT}/launchd/com.hermes.session-s3-mirror.plist.template"
PLIST_DEST="${HOME}/Library/LaunchAgents/com.hermes.session-s3-mirror.plist"
LOG_DIR="${HERMES_HOME}/logs"
STDOUT_LOG="${LOG_DIR}/session-s3-mirror.log"
STDERR_LOG="${LOG_DIR}/session-s3-mirror.error.log"
SKILL_SRC="${REPO_ROOT}/skills/hermes-s3-env-check"
SKILL_DEST="${HERMES_HOME}/skills/hermes-s3-env-check"

mkdir -p "${LOG_DIR}" "${HOME}/Library/LaunchAgents" "${HERMES_HOME}/skills"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  python3 -m venv "${VENV_DIR}"
fi

"${PYTHON_BIN}" -m pip install --upgrade pip >/dev/null
"${PYTHON_BIN}" -m pip install -e "${REPO_ROOT}" >/dev/null
chmod +x "${RUNNER_SCRIPT}"

rm -rf "${SKILL_DEST}"
cp -R "${SKILL_SRC}" "${SKILL_DEST}"

sed \
  -e "s|__RUNNER__|${RUNNER_SCRIPT}|g" \
  -e "s|__HERMES_HOME__|${HERMES_HOME}|g" \
  -e "s|__WORKDIR__|${REPO_ROOT}|g" \
  -e "s|__STDOUT__|${STDOUT_LOG}|g" \
  -e "s|__STDERR__|${STDERR_LOG}|g" \
  "${PLIST_TEMPLATE}" > "${PLIST_DEST}"

launchctl unload "${PLIST_DEST}" >/dev/null 2>&1 || true
launchctl load "${PLIST_DEST}"

printf 'Installed launch agent: %s\n' "${PLIST_DEST}"
printf 'Installed Hermes skill: %s\n' "${SKILL_DEST}"
printf 'Watcher logs: %s and %s\n' "${STDOUT_LOG}" "${STDERR_LOG}"
printf 'Runner script: %s\n' "${RUNNER_SCRIPT}"

