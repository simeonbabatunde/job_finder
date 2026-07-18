# JobMatchKit Backend

The backend is a FastAPI application that supports resume parsing, job discovery, LLM-based matching, application tracking, generated application materials, password reset, OAuth callbacks, scraper configuration, and optional browser automation.

## Current Stack

- FastAPI
- SQLModel
- PostgreSQL
- LangGraph
- LangChain
- OpenAI, OpenRouter, Gemini, and Ollama provider hooks
- python-jobspy
- Playwright
- uv

## Key Files

- `main.py`: FastAPI app, CORS, startup table creation, router mount.
- `app/api/endpoints.py`: API endpoints for auth, resume upload, preferences, profile, agent, applications, packages, admin, password reset, and OAuth.
- `app/models.py`: SQLModel tables.
- `app/schemas.py`: Pydantic request schemas for public API inputs.
- `app/database.py`: engine, session setup, and lightweight versioned startup migrations.
- `app/agent/state.py`: LangGraph state definition.
- `app/agent/graph.py`: workflow edges.
- `app/agent/nodes.py`: resume parsing, search, fit analysis, submission selection, browser application.
- `app/agent/llm_factory.py`: provider factory.
- `app/services/resume_parser.py`: PDF/DOCX/text extraction.
- `app/services/job_search.py`: JobSpy and configured scraper dispatch.
- `app/services/ats_scraper.py`: target company ATS scraping.
- `app/services/motion_recruitment.py`: custom scraper.
- `app/services/persistence.py`: application upsert/dedupe.
- `app/services/browser_apply.py`: Playwright form fill and optional submit.
- `app/services/email.py`: password reset email dispatch.

## Local Development

With Docker Compose from the repository root:

```bash
docker compose up --build
```

Backend only:

```bash
uv sync
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Backend tests from the repository root:

```bash
docker run --rm \
  -e UV_PROJECT_ENVIRONMENT=/tmp/uv-venv \
  -v "$PWD/backend:/app" \
  -w /app \
  ghcr.io/astral-sh/uv:python3.11-bookworm \
  uv run --frozen --group dev python -m pytest app/tests
```

Full repository preflight from the root:

```bash
./scripts/preflight.sh
```

Default API URL:

```text
http://localhost:8000
```

## Environment

Important variables:

```text
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/jobmatchkit
LLM_PROVIDER=openai
LLM_MODEL=
OPENAI_MODEL=
OPENROUTER_MODEL=
GOOGLE_MODEL=
OLLAMA_MODEL=
OPENAI_API_KEY=
OPENROUTER_API_KEY=
GOOGLE_API_KEY=
SMTP_EMAIL=
SMTP_PASSWORD=
FRONTEND_URL=http://localhost:5173
CORS_ALLOWED_ORIGINS=
AUTH_SECRET_KEY=
AUTH_ACCESS_TOKEN_TTL_SECONDS=3600
AUTH_REFRESH_TOKEN_TTL_SECONDS=2592000
APP_DATA_ENCRYPTION_KEY=
APP_DATA_PREVIOUS_ENCRYPTION_KEYS=
FREE_DAILY_AGENT_RUN_LIMIT=3
PRO_DAILY_AGENT_RUN_LIMIT=50
AGENT_RUNNER_MODE=background
AGENT_WORKER_POLL_SECONDS=2
AGENT_WORKER_HEARTBEAT_SECONDS=10
AGENT_WORKER_HEARTBEAT_STALE_SECONDS=30
AGENT_WORKER_ID=
AGENT_RUN_STALE_MINUTES=120
ENABLE_TRUE_AUTO_SUBMIT=false
TRUE_SUBMIT_PILOT_USER_EMAILS=
TRUE_SUBMIT_PILOT_ATS_TYPES=
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
STRIPE_PRO_PRICE_ID=
PRO_PLAN_PRICE_LABEL=$10/mo
BILLING_SUCCESS_URL=
BILLING_CANCEL_URL=
BILLING_PORTAL_RETURN_URL=
```

Docker Compose also expects:

```text
POSTGRES_USER=
POSTGRES_PASSWORD=
POSTGRES_DB=
VITE_API_URL=
```

## Matching Worker

Local API runs default to background execution. Docker Compose defaults to worker mode and starts a separate `worker` service that claims queued matching runs from the database.

To run worker mode manually:

```bash
AGENT_RUNNER_MODE=worker uv run python -m app.worker
```

The worker writes a heartbeat row while idle and while processing long matching runs. `GET /health/worker` uses that heartbeat to report whether worker mode is ready to drain queued runs.

## CORS

Development defaults to `http://localhost:5173` and `http://127.0.0.1:5173`.
Production-like environments (`APP_ENV=production`, `prod`, or `staging`) must set
`CORS_ALLOWED_ORIGINS` or `FRONTEND_URL` to deployed, non-local origins. Localhost
and wildcard origins are rejected at startup in production-like environments.

## API Surface

Health:

- `GET /health`
- `GET /health/db`
- `GET /health/worker`

Auth and account:

- `POST /auth/login`
- `POST /auth/register`
- `POST /auth/logout`
- `GET /auth/google/login`
- `GET /auth/google/callback`
- `GET /auth/linkedin/login`
- `GET /auth/linkedin/callback`
- `POST /auth/forgot-password`
- `POST /auth/reset-password`
- `GET /user/status`
- `GET /account/export`

Resume, profile, and preferences:

- `POST /upload-resume`
- `GET /profile`
- `POST /profile`
- `GET /application-profile`
- `GET /application-profile/export`
- `GET /application-profile/audit`
- `POST /application-profile`
- `DELETE /application-profile`
- `GET /submission-settings`
- `POST /submission-settings`
- `DELETE /submission-settings`
- `POST /preferences`
- `POST /agent/resume-feedback`

Jobs and matching:

- `GET /search-jobs`
- `POST /agent/run`
- `GET /agent/runs`
- `GET /agent/runs/{run_id}`
- `POST /agent/analyze-single`

Applications:

- `GET /applications?limit=5&sort=date&direction=desc`
- `DELETE /applications`
- `PATCH /applications/{app_id}/status`
- `POST /applications/{app_id}/resolve-link`
- `POST /agent/prepare-application`
- `GET /applications/{app_id}/cover-letter.pdf`

Admin:

- `GET /admin/config`
- `PUT /admin/config`

## Matching Workflow

The LangGraph workflow is:

1. `parse_resume`
2. `search_jobs`
3. `analyze_fit`
4. `submit_application`

The workflow currently:

- extracts resume summary and skills
- searches job boards and target company career pages
- runs a conservative pre-screen that rejects only obvious non-fits before LLM analysis
- analyzes pass/maybe jobs in a batch LLM call
- persists job records incrementally, including review-only screened-out records with reasons
- selects jobs above the minimum match score

`GET /applications` also accepts `match_bucket=strong|below_threshold|screened_out|all`.
The dashboard uses `strong` by default so below-threshold and screened-out jobs stay out of
the main best-fit view while remaining reviewable from the full pipeline.

## Current Data Models

- `Resume`
- `JobPreference`
- `User`
- `Application`
- `AgentRun`
- `WorkerHeartbeat`
- `AutoApplyAttempt`
- `AutoApplyAudit`
- `ApplicationFillReview`
- `ApplicationSubmitSettings`
- `ApplicationAnswerProfile`
- `ApplicationAnswerAudit`
- `Profile`
- `ScraperConfig`
- `PasswordResetToken`

## Known Backend Issues

- Authentication uses signed bearer tokens plus rotating refresh tokens, server-side session invalidation, refresh replay protection, and previous-secret verification for key rotation.
- The previous README contained a plaintext OpenRouter key. It has been removed; rotate the key if it was real.
- Database startup can run an Alembic baseline when `USE_ALEMBIC_MIGRATIONS=true`; local/dev still defaults to the lightweight `schema_migrations` runner.
- Core public write endpoints use Pydantic request schemas, and the main app/API responses now have explicit response models.
- Daily matching-run quotas are enforced for free/pro tiers, and Stripe Checkout/Portal/webhooks manage paid Pro status when billing env vars are set.
- Matching runs are queued through FastAPI background tasks and persisted for polling.
- Matching runs and worker claims emit structured JSON operational logs. Set `STRUCTURED_LOG_LEVEL` to tune verbosity.
- Browser automation entry points have been retired and now return `410 Gone`; users open employer links manually from saved matches.
- Application answer-vault string fields are encrypted at rest with `APP_DATA_ENCRYPTION_KEY`; development falls back to the auth secret, but production requires the dedicated key.
- `APP_DATA_PREVIOUS_ENCRYPTION_KEYS` keeps old encrypted answer-vault rows readable during data-key rotation while new saves use the current key.
- After data-key rotation, run the answer-vault re-encryption job before removing old previous keys:
  - `uv run python -m app.jobs.reencrypt_application_answers --dry-run`
  - `uv run python -m app.jobs.reencrypt_application_answers --apply`
- Application answer-vault export, view, reset, and dashboard preload events are audited without storing answer values in the audit log.
- `GET /account/export` returns a signed-in user's resumes, preferences, profile, application answers, generated package records, application history, matching runs, and audit records.
- Health endpoints expose API liveness, DB reachability, and worker heartbeat freshness without returning user data.
- LLM calls are live by default and need test doubles for repeatable automated tests.

## Backend Implementation Priorities

1. Run `./scripts/preflight.sh` before staging pushes or broad feature branches.
2. Enable Alembic in staging, validate the baseline against an existing database, then retire the lightweight runner when production migration history is trusted.
3. Run the answer-vault re-encryption job and confirm a clean dry run before removing old `APP_DATA_PREVIOUS_ENCRYPTION_KEYS`.
4. Keep true final submit disabled by default until a real-submit pilot is explicitly approved.
5. Follow `docs/DEPLOYMENT_READINESS.md` before sharing a hosted staging environment.

## Product Notes Preserved

The original goal remains:

Build an LLM-powered app that can analyze a user's resume, compare it to job postings, submit or prepare applications for the best matches, support enterprise and local LLM providers, offer subscription tiers, and show application history and status.

The current product expectation is that the user should not need separate "Analyze Resume" or "Save Preferences" actions before starting a match. The matching workflow should save and analyze the required setup data as part of the process.
