# Hermes Session S3

External Hermes integration that mirrors `~/.hermes/sessions/*` into S3-compatible
storage for debugging and audit use cases.

This repository intentionally lives outside `hermes-agent`:
- `skills/hermes-s3-env-check/` validates that the required env vars are configured
- `src/hermes_session_s3/` contains the standalone sync helper
- `scripts/install_launch_agent.sh` installs a per-user `launchd` job on macOS

## Environment contract

Required:
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `FREE_CODE_LOGS_S3_BUCKET`

Optional defaults:
- `AWS_ENDPOINT_URL=https://s3.cloud.ru`
- `AWS_DEFAULT_REGION=ru-central-1`
- `HERMES_SESSIONS_S3_PREFIX=hermes-sessions`

## Local setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

## Commands

Validate env:

```bash
skills/hermes-s3-env-check/scripts/check_hermes_s3_env.sh
```

One-shot sync:

```bash
.venv/bin/python -m hermes_session_s3.cli sync-once
```

Continuous sync:

```bash
.venv/bin/python -m hermes_session_s3.cli watch
```

Install local Hermes skill and launchd service:

```bash
scripts/install_launch_agent.sh
```

