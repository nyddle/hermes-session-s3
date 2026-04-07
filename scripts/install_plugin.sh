#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
PLUGIN_DEST="${HERMES_HOME}/plugins/hermes-session-s3"
SKILL_SRC="${REPO_ROOT}/skills/hermes-s3-env-check"
SKILL_DEST="${HERMES_HOME}/skills/hermes-s3-env-check"

mkdir -p "${HERMES_HOME}/plugins" "${HERMES_HOME}/skills"

rm -rf "${PLUGIN_DEST}"
ln -s "${REPO_ROOT}" "${PLUGIN_DEST}"

rm -rf "${SKILL_DEST}"
cp -R "${SKILL_SRC}" "${SKILL_DEST}"

printf 'Installed Hermes plugin symlink: %s -> %s\n' "${PLUGIN_DEST}" "${REPO_ROOT}"
printf 'Installed Hermes skill: %s\n' "${SKILL_DEST}"

