#!/usr/bin/env bash

set -euo pipefail

PLIST_DEST="${HOME}/Library/LaunchAgents/com.hermes.session-s3-mirror.plist"

launchctl unload "${PLIST_DEST}" >/dev/null 2>&1 || true
rm -f "${PLIST_DEST}"

printf 'Removed launch agent: %s\n' "${PLIST_DEST}"
