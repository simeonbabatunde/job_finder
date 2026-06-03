# Deployment Readiness

Use this checklist before sharing a hosted staging build or storing real user data.

## Required Services

- Frontend: Vite React app.
- API: FastAPI backend.
- Worker: `python -m app.worker` when `AGENT_RUNNER_MODE=worker`.
- Database: PostgreSQL.

Docker Compose runs all four services locally:

```bash
docker compose up --build
```

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
- current agent run id when available
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
4. Smoke-test auth, resume upload, preferences, agent queueing, application package generation, and artifact download.

When `USE_ALEMBIC_MIGRATIONS=true`, startup migrations take a Postgres advisory
lock so the API and worker can start at the same time without racing the Alembic
version table.

Local staging rehearsal with Docker Compose:

```bash
APP_ENV=staging \
AUTH_SECRET_KEY=<32+ random characters> \
APP_DATA_ENCRYPTION_KEY=<32+ random characters> \
FRONTEND_URL=https://staging-job-finder.example.com \
CORS_ALLOWED_ORIGINS=https://staging-job-finder.example.com \
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
docker compose exec db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/job_finder.backup
docker cp job_finder-db-1:/tmp/job_finder.backup backups/job_finder.backup
```

Local restore rehearsal against a disposable database:

```bash
docker compose exec db createdb -U "$POSTGRES_USER" job_hunter_restore_check
docker cp backups/job_finder.backup job_finder-db-1:/tmp/job_finder.backup
docker compose exec db pg_restore -U "$POSTGRES_USER" -d job_hunter_restore_check --clean --if-exists /tmp/job_finder.backup
docker compose exec db dropdb -U "$POSTGRES_USER" job_hunter_restore_check
```

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
5. Keep previous keys until old rows have been re-saved or a dedicated re-encryption job exists.

Provider, SMTP, and OAuth keys should be rotated in the provider console and stored
only in the hosting secret manager.

## Docker E2E Smoke

After `docker compose up --build`, verify:

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
5. Run the search assistant.
6. Open a matched job and generate the application package.
7. Download the generated package and cover-letter PDF.

## Production Gates

- Keep `ENABLE_TRUE_AUTO_SUBMIT=false` until a controlled pilot is approved.
- Confirm `/health/worker` is healthy before relying on queued agent runs.
- Confirm CORS allows only the deployed frontend origin.
- Confirm Postgres credentials are not local defaults.
- Confirm backups and restore testing before storing real resumes or application answers.
- Confirm screenshot and trace retention with `FILL_REVIEW_ARTIFACT_RETENTION_DAYS`.
- Confirm answer-vault export and audit history work for the signed-in user only.
