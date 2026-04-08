# Hermes Session S3

External Hermes integration for debugging and audit:
- a Hermes plugin writes `request_dump_*.json` and `response_dump_*.json`
- the same plugin uploads those dumps to S3 in the same layout as free_code

This repository intentionally lives outside `hermes-agent`:
- `plugin.yaml` + `__init__.py` make the repo loadable as a Hermes plugin
- `skills/hermes-s3-env-check/` validates that the required env vars are configured
- `src/hermes_session_s3/` contains the dump and S3 mirror logic

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

Install the plugin locally for Hermes:

```bash
scripts/install_plugin.sh
```

For teammates with a remote repo URL, the preferred install path is Hermes itself:

```bash
hermes plugins install <git-url-to-this-repo>
```

Optional standalone sync commands still exist for local testing:

```bash
.venv/bin/python -m hermes_session_s3.cli sync-once
.venv/bin/python -m hermes_session_s3.cli watch
```

When the plugin is installed and the required S3 env vars are present, Hermes
will:
- write `request_dump_*.json` before provider calls
- write `response_dump_*.json` after provider calls
- upload only request/response dumps plus `README.md` to S3

## S3 layout

The uploaded objects follow the same layout as free_code:

```text
<prefix>/<YYYY-MM>-<username>/<session-id>/<timestamp>_<id>_request.json
<prefix>/<YYYY-MM>-<username>/<session-id>/<timestamp>_<id>_response.json
<prefix>/<YYYY-MM>-<username>/<session-id>/README.md
```

Hermes session transcripts such as `session_*.json` and `*.jsonl` remain local
and are no longer mirrored into S3.
