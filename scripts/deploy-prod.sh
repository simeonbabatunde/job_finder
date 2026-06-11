#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-.env.production}"
RUN_HEALTH_CHECKS="${RUN_HEALTH_CHECKS:-1}"

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE. Copy .env.production.example and fill real production values first." >&2
  exit 1
fi

env_value() {
  local key="$1"
  awk -F= -v key="$key" '
    $1 == key {
      sub(/^[^=]*=/, "")
      gsub(/^"|"$/, "")
      print
      exit
    }
  ' "$ENV_FILE"
}

compose=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")

"${compose[@]}" build
"${compose[@]}" up -d
"${compose[@]}" ps

if [ "$RUN_HEALTH_CHECKS" != "1" ]; then
  echo "Skipped health checks because RUN_HEALTH_CHECKS=$RUN_HEALTH_CHECKS."
  exit 0
fi

check_internal_health() {
  local path="$1"
  local label="$2"
  local attempt

  for attempt in $(seq 1 30); do
    if "${compose[@]}" exec -T backend curl -fsS "http://localhost:8000${path}" >/dev/null; then
      echo "OK: ${label}"
      return 0
    fi
    sleep 2
  done

  echo "Health check failed: ${label}" >&2
  return 1
}

check_internal_health "/health" "API process"
check_internal_health "/health/db" "database"
check_internal_health "/health/worker" "worker heartbeat"

app_domain="${APP_DOMAIN:-$(env_value APP_DOMAIN)}"
if [ -n "$app_domain" ] && command -v curl >/dev/null 2>&1; then
  app_domain="${app_domain%%,*}"
  health_url="${HEALTH_URL:-https://${app_domain}/api/health}"
  if curl -fsS "$health_url" >/dev/null; then
    echo "OK: public health endpoint ${health_url}"
  else
    echo "Public health check did not pass yet: ${health_url}" >&2
    echo "If this is a first deploy, verify DNS points to the VPS and Caddy has issued the certificate." >&2
  fi
fi
