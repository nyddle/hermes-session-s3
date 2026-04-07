---
name: hermes-s3-env-check
description: Validate Hermes S3 session-upload environment variables. Use when the user wants to check whether ~/.hermes/.env or the current shell has the required AWS and bucket variables for uploading ~/.hermes/sessions/* to S3, and print exactly which variables are missing plus the defaults used for optional ones.
version: 1.0.0
required_environment_variables:
  - name: AWS_ACCESS_KEY_ID
    prompt: Enter AWS access key ID for the S3-compatible storage
    required_for: Uploading Hermes session files to S3
  - name: AWS_SECRET_ACCESS_KEY
    prompt: Enter AWS secret access key for the S3-compatible storage
    required_for: Uploading Hermes session files to S3
  - name: FREE_CODE_LOGS_S3_BUCKET
    prompt: Enter the S3 bucket name used for Hermes session uploads
    required_for: Uploading Hermes session files to S3
metadata:
  hermes:
    tags: [s3, env, sessions, debugging, audit]
    related_skills: []
---

# Hermes S3 Env Check

Use this skill to verify that the external Hermes session S3 plugin is ready to
mirror `~/.hermes/sessions/*` into S3-compatible storage.

## What to do

Run the bundled checker:

```bash
scripts/check_hermes_s3_env.sh
```

When the required env vars are present and the `hermes-session-s3` plugin is
installed, Hermes can mirror `~/.hermes/sessions/*` into S3 on session end.

The checker reads:
- the current process environment
- `~/.hermes/.env` by default

It validates this contract.

Required:
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `FREE_CODE_LOGS_S3_BUCKET`

Optional with defaults:
- `AWS_ENDPOINT_URL` -> `https://s3.cloud.ru`
- `AWS_DEFAULT_REGION` -> `ru-central-1`

## Response guidance

After running the checker:
- Tell the user whether the configuration is ready.
- List missing required variables first.
- If something is missing, include the exact env block printed by the script.
- Do not print secret values back to the user.

## Notes

- Prefer the script output over manual inspection.
- If the user wants a different env file, run the checker with
  `HERMES_ENV_FILE=/path/to/.env scripts/check_hermes_s3_env.sh`.
