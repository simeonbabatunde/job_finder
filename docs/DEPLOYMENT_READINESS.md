# Deployment Readiness

Use this checklist before sharing a hosted staging build or storing real user data.
For step-by-step operating procedures, see `docs/OPERATIONS_RUNBOOK.md`.
For the first production VPS launch path, see `docs/VPS_DEPLOYMENT.md`.
For hands-on product validation, use `docs/MANUAL_QA_CHECKLIST.md`.

## Required Services

- Frontend: Vite React app.
- API: FastAPI backend.
- Worker: `python -m app.worker` when `AGENT_RUNNER_MODE=worker`.
- Database: PostgreSQL.

Docker Compose runs all four services locally:

```bash
docker compose up --build
```

Production VPS deployments use `docker-compose.prod.yml`, `Caddyfile`,
`frontend/Dockerfile.prod`, and `.env.production`. Local development should keep
using the default `docker-compose.yml`.

## Launch Preflight

Run this command before sharing a staging build, pushing a larger feature branch,
or testing real user data:

```bash
./scripts/preflight.sh
```

It performs the current launch-readiness gate:

- Dockerized backend tests.
- Frontend dependency install when needed, lint, and production build.
- `docker compose config` rendering with safe development defaults.
- Isolated Alembic `upgrade head` against a disposable SQLite database.
- Docker Compose `up --build -d`.
- `/health`, `/health/db`, `/health/worker`, and frontend HTTP readiness checks.
- Answer-vault save, export, and audit smoke test with a throwaway local user.
- Signed-in browser dashboard smoke test with a throwaway local user.

By default, the command leaves the Compose stack running for browser testing at
`http://localhost:5173`. For CI or a disposable local check, use:

```bash
PREFLIGHT_COMPOSE_DOWN_ON_EXIT=1 ./scripts/preflight.sh
```

The smoke test does not call live LLMs or live job scrapers, and true final
submission remains blocked by `ENABLE_TRUE_AUTO_SUBMIT=false`.

## Health Checks

The backend exposes public, non-sensitive deployment checks:

- `GET /health`: API process liveness.
- `GET /health/db`: database reachability and migration mode.
- `GET /health/worker`: queue counts, stale run counts, and worker heartbeat freshness.

Expected local Docker checks:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/health/db
curl http://localhost:8000/health/worker
```

`/health/worker` returns HTTP 503 when `AGENT_RUNNER_MODE=worker` and no fresh worker heartbeat exists. In `background` mode, a missing worker is acceptable and the endpoint should remain healthy.

The response separates heartbeat freshness from the worker's own state: `heartbeat_status` is `fresh`, `stale`, `missing`, or `not_expected`; `heartbeat_worker_status` is the worker-reported state such as `idle`, `running`, or `error`.

## Worker Heartbeats

The worker writes one `WorkerHeartbeat` row per process. This row contains:

- worker id
- status: `starting`, `polling`, `idle`, `running`, or `error`
- last seen timestamp
- current matching run id when available
- small operational details such as heartbeat interval

Environment knobs:

```text
AGENT_RUNNER_MODE=worker
AGENT_WORKER_POLL_SECONDS=2
AGENT_WORKER_HEARTBEAT_SECONDS=10
AGENT_WORKER_HEARTBEAT_STALE_SECONDS=30
AGENT_WORKER_ID=
AGENT_RUN_STALE_MINUTES=120
```

Leave `AGENT_WORKER_ID` blank for single-container local runs so each worker derives a unique id. Set it only when the hosting platform already provides a stable unique worker identifier.

## Staging Environment

Set these before a hosted staging run:

```text
APP_ENV=production
AUTH_SECRET_KEY=<32+ random characters>
AUTH_PREVIOUS_SECRET_KEYS=
APP_DATA_ENCRYPTION_KEY=<32+ random characters>
APP_DATA_PREVIOUS_ENCRYPTION_KEYS=
DATABASE_URL=<staging postgres url>
FRONTEND_URL=<staging frontend origin>
CORS_ALLOWED_ORIGINS=<staging frontend origin>
VITE_API_URL=<staging api origin>
USE_ALEMBIC_MIGRATIONS=true
ENABLE_TRUE_AUTO_SUBMIT=false
TRUE_SUBMIT_PILOT_USER_EMAILS=
TRUE_SUBMIT_PILOT_ATS_TYPES=
LLM_PROVIDER=openai
LLM_MODEL=
OPENAI_MODEL=
OPENROUTER_MODEL=
GOOGLE_MODEL=
OLLAMA_MODEL=
```

Also set provider and email keys only in the hosting secret manager:

```text
OPENAI_API_KEY=
OPENROUTER_API_KEY=
GOOGLE_API_KEY=
SMTP_EMAIL=
SMTP_PASSWORD=
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
LINKEDIN_CLIENT_ID=
LINKEDIN_CLIENT_SECRET=
```

Keep `.env` local and private. Use `.env.example` only as a placeholder template.

`APP_ENV=staging` is production-like: weak auth secrets, missing data-encryption keys,
localhost CORS origins, and wildcard CORS origins are rejected at startup.

## Migration Path

Local development defaults to the lightweight startup migration runner. Staging should use:

```text
USE_ALEMBIC_MIGRATIONS=true
```

Before enabling that against an existing database:

1. Restore a copy of the database into a staging-like environment.
2. Run Alembic upgrade against the copy.
3. Verify `/health/db` reports `migration_mode: "alembic"`.
4. Smoke-test auth, resume upload, preferences, matching workflow queueing, application package generation, and artifact download.

When `USE_ALEMBIC_MIGRATIONS=true`, startup migrations take a Postgres advisory
lock so the API and worker can start at the same time without racing the Alembic
version table.

Local staging rehearsal with Docker Compose:

```bash
APP_ENV=staging \
AUTH_SECRET_KEY=<32+ random characters> \
APP_DATA_ENCRYPTION_KEY=<32+ random characters> \
FRONTEND_URL=https://staging.jobmatchkit.com \
CORS_ALLOWED_ORIGINS=https://staging.jobmatchkit.com \
USE_ALEMBIC_MIGRATIONS=true \
docker compose up --build -d backend worker
```

Then verify:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/health/db
curl http://localhost:8000/health/worker
```

`/health/db` should report `migration_mode: "alembic"`.

## CORS

Development can use the local frontend origins. Production-like environments must
set `CORS_ALLOWED_ORIGINS` or `FRONTEND_URL` to deployed HTTPS frontend origins.
The backend rejects wildcard and localhost CORS origins when `APP_ENV` is
`production`, `prod`, or `staging`.

Use `CORS_ALLOWED_ORIGINS` when more than one deployed frontend origin is needed:

```text
CORS_ALLOWED_ORIGINS=https://app.example.com,https://preview.example.com
```

## Backup And Restore

Before storing real resumes or application answers, prove restore works against a
copy of the database. Do not commit backup artifacts.

Local Compose backup example:

```bash
mkdir -p backups
docker compose exec db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/jobmatchkit.backup
docker cp jobmatchkit-db-1:/tmp/jobmatchkit.backup backups/jobmatchkit.backup
```

Local restore rehearsal against a disposable database:

```bash
docker compose exec db createdb -U "$POSTGRES_USER" jobmatchkit_restore_check
docker cp backups/jobmatchkit.backup jobmatchkit-db-1:/tmp/jobmatchkit.backup
docker compose exec db pg_restore -U "$POSTGRES_USER" -d jobmatchkit_restore_check --clean --if-exists /tmp/jobmatchkit.backup
docker compose exec db dropdb -U "$POSTGRES_USER" jobmatchkit_restore_check
```

For local machines that already ran the app before the JobMatchKit rebrand,
old data may be under pre-rebrand database, Compose project, or volume names.
Take a backup before changing database env vars or renaming the project folder,
then restore into `jobmatchkit` if you want to keep that local data.

For managed Postgres, use the provider's snapshot/restore tooling plus one manual
restore rehearsal before launch.

## Secret Rotation

Auth token signing supports a rolling rotation:

1. Move the current `AUTH_SECRET_KEY` into `AUTH_PREVIOUS_SECRET_KEYS`.
2. Set a new strong `AUTH_SECRET_KEY`.
3. Deploy.
4. Wait longer than `AUTH_REFRESH_TOKEN_TTL_SECONDS`.
5. Remove the previous key.

Answer-vault encryption supports previous data keys for reads:

1. Move the current `APP_DATA_ENCRYPTION_KEY` into `APP_DATA_PREVIOUS_ENCRYPTION_KEYS`.
2. Set a new strong `APP_DATA_ENCRYPTION_KEY`.
3. Deploy.
4. New or updated answer-vault saves use the new key.
5. Run a dry run:
   `docker compose exec -T backend uv run python -m app.jobs.reencrypt_application_answers --dry-run`
6. Confirm `unreadable_records` is `0`, then apply:
   `docker compose exec -T backend uv run python -m app.jobs.reencrypt_application_answers --apply`
7. Run the dry run again and confirm `previous_key_records`, `plaintext_records`, and `unreadable_records` are all `0`.
8. Remove old `APP_DATA_PREVIOUS_ENCRYPTION_KEYS` only after a backup exists and the post-apply dry run is clean.

Provider, SMTP, and OAuth keys should be rotated in the provider console and stored
only in the hosting secret manager.

## Docker E2E Smoke

The preferred repeatable E2E smoke is:

```bash
./scripts/preflight.sh
```

For a manual check after `docker compose up --build`, verify:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/health/db
curl http://localhost:8000/health/worker
```

Then use the frontend at `http://localhost:5173`:

1. Register or sign in.
2. Save profile, application answers, and job preferences.
3. Upload a resume.
4. Export application answers and confirm the answer-vault audit list records the export.
5. Export account data and confirm the downloaded JSON contains only the signed-in user's records.
6. Run the search assistant.
7. Open a matched job and generate the application package.
8. Download the generated package and cover-letter PDF.

## Production Gates

- Keep `ENABLE_TRUE_AUTO_SUBMIT=false` until a controlled pilot is approved; when a pilot is approved, scope it with `TRUE_SUBMIT_PILOT_USER_EMAILS` and optionally `TRUE_SUBMIT_PILOT_ATS_TYPES`.
- Confirm `/health/worker` is healthy before relying on queued matching runs.
- Confirm CORS allows only the deployed frontend origin.
- Confirm Postgres credentials are not local defaults.
- Confirm backups and restore testing before storing real resumes or application answers.
- Confirm answer-vault export and audit history work for the signed-in user only.
- Confirm account data export works for the signed-in user only and is treated as private user data.
