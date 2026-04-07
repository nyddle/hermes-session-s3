#!/usr/bin/env bash

set -euo pipefail

ENV_FILE="${HERMES_ENV_FILE:-$HOME/.hermes/.env}"

required_vars=(
  "AWS_ACCESS_KEY_ID"
  "AWS_SECRET_ACCESS_KEY"
  "FREE_CODE_LOGS_S3_BUCKET"
)

optional_vars=(
  "AWS_ENDPOINT_URL"
  "AWS_DEFAULT_REGION"
)

default_for() {
  case "$1" in
    AWS_ENDPOINT_URL) printf '%s' 'https://s3.cloud.ru' ;;
    AWS_DEFAULT_REGION) printf '%s' 'ru-central-1' ;;
    *) return 1 ;;
  esac
}

trim() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

strip_quotes() {
  local value
  value="$(trim "$1")"

  if [[ "$value" == \"*\" && "$value" == *\" ]]; then
    value="${value:1:${#value}-2}"
  elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
    value="${value:1:${#value}-2}"
  else
    value="${value%%#*}"
    value="$(trim "$value")"
  fi

  printf '%s' "$value"
}

read_from_env_file() {
  local key="$1"

  if [[ ! -f "$ENV_FILE" ]]; then
    return 0
  fi

  awk -v key="$key" '
    BEGIN {
      pattern = "^[[:space:]]*(export[[:space:]]+)?" key "[[:space:]]*="
    }
    $0 ~ pattern {
      line = $0
      sub(/^[[:space:]]*(export[[:space:]]+)?[^=]+=[[:space:]]*/, "", line)
      print line
    }
  ' "$ENV_FILE" | tail -n 1
}

resolve_var() {
  local key="$1"
  local current_value="${!key-}"
  if [[ -n "$current_value" ]]; then
    printf '%s\t%s\n' "$current_value" 'current environment'
    return 0
  fi

  local raw_file_value
  raw_file_value="$(read_from_env_file "$key")"
  local file_value
  file_value="$(strip_quotes "$raw_file_value")"
  if [[ -n "$file_value" ]]; then
    printf '%s\t%s\n' "$file_value" "$ENV_FILE"
    return 0
  fi

  printf '\t\n'
}

print_status_line() {
  local key="$1"
  local value="$2"
  local source="$3"
  local default_value="${4-}"

  if [[ -n "$value" ]]; then
    printf 'OK       %s (%s)\n' "$key" "$source"
    return 0
  fi

  if [[ -n "$default_value" ]]; then
    printf 'DEFAULT  %s=%s\n' "$key" "$default_value"
    return 0
  fi

  printf 'MISSING  %s\n' "$key"
}

print_env_block() {
  cat <<'EOF'
export AWS_ACCESS_KEY_ID=""
export AWS_SECRET_ACCESS_KEY=""
export AWS_ENDPOINT_URL="https://s3.cloud.ru"
export AWS_DEFAULT_REGION="ru-central-1"
export FREE_CODE_LOGS_S3_BUCKET="bucket-claude-logs"
EOF
}

missing_required=()

printf 'Hermes S3 env check\n'
printf 'Env file: %s\n' "$ENV_FILE"
if [[ -f "$ENV_FILE" ]]; then
  printf 'Env file status: found\n'
else
  printf 'Env file status: not found\n'
fi
printf '\n'

for key in "${required_vars[@]}"; do
  resolved="$(resolve_var "$key")"
  value="${resolved%%$'\t'*}"
  source="${resolved#*$'\t'}"
  print_status_line "$key" "$value" "$source"
  if [[ -z "$value" ]]; then
    missing_required+=("$key")
  fi
done

for key in "${optional_vars[@]}"; do
  resolved="$(resolve_var "$key")"
  value="${resolved%%$'\t'*}"
  source="${resolved#*$'\t'}"
  default_value="$(default_for "$key")"
  if [[ -n "$value" ]]; then
    print_status_line "$key" "$value" "$source"
  else
    print_status_line "$key" "" "" "$default_value"
  fi
done

printf '\n'

if [[ "${#missing_required[@]}" -eq 0 ]]; then
  printf 'Ready: required Hermes S3 variables are configured.\n'
  exit 0
fi

printf 'Missing required variables:\n'
for key in "${missing_required[@]}"; do
  printf -- '- %s\n' "$key"
done

printf '\nSuggested block for %s:\n' "$ENV_FILE"
print_env_block

exit 1

