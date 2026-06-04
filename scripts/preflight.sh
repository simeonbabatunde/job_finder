#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UV_IMAGE="${PREFLIGHT_UV_IMAGE:-ghcr.io/astral-sh/uv:python3.11-bookworm}"
API_URL="${PREFLIGHT_API_URL:-http://127.0.0.1:8000}"
FRONTEND_HEALTH_URL="${PREFLIGHT_FRONTEND_URL:-http://localhost:5173}"

export POSTGRES_USER="${POSTGRES_USER:-postgres}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-postgres}"
export POSTGRES_DB="${POSTGRES_DB:-job_hunter}"
export DATABASE_URL="${DATABASE_URL:-postgresql://postgres:postgres@db:5432/job_hunter}"
export FRONTEND_URL="${FRONTEND_URL:-http://localhost:5173}"
export VITE_API_URL="${VITE_API_URL:-http://localhost:8000}"
export CORS_ALLOWED_ORIGINS="${CORS_ALLOWED_ORIGINS:-http://localhost:5173,http://127.0.0.1:5173,http://frontend:5173}"
export APP_ENV="${APP_ENV:-development}"
export AUTH_SECRET_KEY="${AUTH_SECRET_KEY:-job-finder-dev-secret-change-me}"
export AUTH_PREVIOUS_SECRET_KEYS="${AUTH_PREVIOUS_SECRET_KEYS:-}"
export AUTH_ACCESS_TOKEN_TTL_SECONDS="${AUTH_ACCESS_TOKEN_TTL_SECONDS:-3600}"
export AUTH_REFRESH_TOKEN_TTL_SECONDS="${AUTH_REFRESH_TOKEN_TTL_SECONDS:-2592000}"
export APP_DATA_ENCRYPTION_KEY="${APP_DATA_ENCRYPTION_KEY:-}"
export APP_DATA_PREVIOUS_ENCRYPTION_KEYS="${APP_DATA_PREVIOUS_ENCRYPTION_KEYS:-}"
export FREE_DAILY_AGENT_RUN_LIMIT="${FREE_DAILY_AGENT_RUN_LIMIT:-3}"
export PRO_DAILY_AGENT_RUN_LIMIT="${PRO_DAILY_AGENT_RUN_LIMIT:-50}"
export FILL_REVIEW_ARTIFACT_DIR="${FILL_REVIEW_ARTIFACT_DIR:-storage/fill_review_artifacts}"
export FILL_REVIEW_ARTIFACT_RETENTION_DAYS="${FILL_REVIEW_ARTIFACT_RETENTION_DAYS:-14}"
export USE_ALEMBIC_MIGRATIONS="${USE_ALEMBIC_MIGRATIONS:-false}"
export AGENT_RUNNER_MODE="${AGENT_RUNNER_MODE:-worker}"
export AGENT_WORKER_POLL_SECONDS="${AGENT_WORKER_POLL_SECONDS:-2}"
export AGENT_WORKER_HEARTBEAT_SECONDS="${AGENT_WORKER_HEARTBEAT_SECONDS:-10}"
export AGENT_WORKER_HEARTBEAT_STALE_SECONDS="${AGENT_WORKER_HEARTBEAT_STALE_SECONDS:-30}"
export AGENT_RUN_STALE_MINUTES="${AGENT_RUN_STALE_MINUTES:-120}"
export ENABLE_TRUE_AUTO_SUBMIT="${ENABLE_TRUE_AUTO_SUBMIT:-false}"
export TRUE_SUBMIT_PILOT_USER_EMAILS="${TRUE_SUBMIT_PILOT_USER_EMAILS:-}"
export TRUE_SUBMIT_PILOT_ATS_TYPES="${TRUE_SUBMIT_PILOT_ATS_TYPES:-}"
export OPENAI_API_KEY="${OPENAI_API_KEY:-}"
export OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}"
export GOOGLE_API_KEY="${GOOGLE_API_KEY:-}"
export SMTP_EMAIL="${SMTP_EMAIL:-}"
export SMTP_PASSWORD="${SMTP_PASSWORD:-}"

section() {
  printf '\n==> %s\n' "$1"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "$1" >&2
    exit 1
  fi
}

dump_compose_logs() {
  if [[ "${PREFLIGHT_DUMP_LOGS_ON_ERROR:-1}" != "1" ]]; then
    return
  fi

  printf '\nDocker Compose status after failure:\n' >&2
  docker compose ps >&2 || true
  printf '\nRecent backend/worker/frontend logs:\n' >&2
  docker compose logs --tail=100 backend worker frontend >&2 || true
}

on_error() {
  local exit_code=$?
  dump_compose_logs
  exit "$exit_code"
}

on_exit() {
  if [[ "${PREFLIGHT_COMPOSE_DOWN_ON_EXIT:-0}" == "1" ]]; then
    docker compose down -v >/dev/null 2>&1 || true
  fi
}

trap on_error ERR
trap on_exit EXIT

wait_for_http() {
  local label="$1"
  local url="$2"
  local attempts="${3:-45}"
  local delay_seconds="${4:-2}"

  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if curl --fail --silent --max-time 5 "$url" >/dev/null 2>&1; then
      printf '%s is ready: %s\n' "$label" "$url"
      return 0
    fi
    sleep "$delay_seconds"
  done

  printf 'Timed out waiting for %s at %s\n' "$label" "$url" >&2
  curl --silent --show-error --max-time 10 "$url" >&2 || true
  return 1
}

run_backend_uv() {
  docker run --rm \
    -e UV_PROJECT_ENVIRONMENT=/tmp/uv-venv \
    -v "$ROOT_DIR/backend:/app" \
    -w /app \
    "$UV_IMAGE" \
    uv run --frozen --group dev "$@"
}

require_command docker
require_command node
require_command npm
require_command curl

section "Backend API contract tests"
run_backend_uv python -m pytest app/tests/test_api_contracts.py

section "Frontend dependencies"
if [[ ! -d "$ROOT_DIR/frontend/node_modules" ]]; then
  npm --prefix "$ROOT_DIR/frontend" ci
fi

section "Frontend lint"
npm --prefix "$ROOT_DIR/frontend" run lint

section "Frontend build"
npm --prefix "$ROOT_DIR/frontend" run build

section "Docker Compose config"
docker compose config >/dev/null

section "Alembic isolated upgrade"
ALEMBIC_TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/job_finder_preflight_alembic.XXXXXX")"
trap 'rm -rf "$ALEMBIC_TMP_DIR"; on_exit' EXIT
docker run --rm \
  -e UV_PROJECT_ENVIRONMENT=/tmp/uv-venv \
  -e DATABASE_URL=sqlite:////preflight/job_finder_alembic.db \
  -v "$ROOT_DIR/backend:/app" \
  -v "$ALEMBIC_TMP_DIR:/preflight" \
  -w /app \
  "$UV_IMAGE" \
  uv run --frozen --group dev alembic -c alembic.ini upgrade head

section "Docker Compose services"
docker compose up --build -d

section "Health checks"
wait_for_http "Backend API" "$API_URL/health"
wait_for_http "Database health" "$API_URL/health/db"
wait_for_http "Worker health" "$API_URL/health/worker" 60 2
wait_for_http "Frontend" "$FRONTEND_HEALTH_URL" 60 2

section "Answer-vault export and audit smoke"
PREFLIGHT_API_URL="$API_URL" node "$ROOT_DIR/scripts/preflight-answer-audit.mjs"

section "Frontend dashboard browser smoke"
docker compose exec -T \
  -e PREFLIGHT_API_URL=http://localhost:8000 \
  -e PREFLIGHT_FRONTEND_BROWSER_URL=http://frontend:5173 \
  backend uv run python -m app.smoke.frontend_dashboard

section "Preflight complete"
printf 'All launch-readiness checks passed.\n'
