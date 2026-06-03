# Job Finder Backend

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

Backend tests:

```bash
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -e backend pytest
PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/app/tests/test_api_contracts.py
```

Default API URL:

```text
http://localhost:8000
```

## Environment

Important variables:

```text
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/job_hunter
OPENAI_API_KEY=
OPENROUTER_API_KEY=
GOOGLE_API_KEY=
SMTP_EMAIL=
SMTP_PASSWORD=
FRONTEND_URL=http://localhost:5173
AUTH_SECRET_KEY=
AUTH_ACCESS_TOKEN_TTL_SECONDS=3600
AUTH_REFRESH_TOKEN_TTL_SECONDS=2592000
APP_DATA_ENCRYPTION_KEY=
FREE_DAILY_AGENT_RUN_LIMIT=3
PRO_DAILY_AGENT_RUN_LIMIT=50
FILL_REVIEW_ARTIFACT_DIR=storage/fill_review_artifacts
FILL_REVIEW_ARTIFACT_RETENTION_DAYS=14
AGENT_RUNNER_MODE=background
AGENT_WORKER_POLL_SECONDS=2
AGENT_RUN_STALE_MINUTES=120
ENABLE_TRUE_AUTO_SUBMIT=false
```

Docker Compose also expects:

```text
POSTGRES_USER=
POSTGRES_PASSWORD=
POSTGRES_DB=
VITE_API_URL=
```

## Agent Worker

Local API runs default to background execution. Docker Compose defaults to worker mode and starts a separate `worker` service that claims queued agent runs from the database.

To run worker mode manually:

```bash
AGENT_RUNNER_MODE=worker uv run python -m app.worker
```

## API Surface

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

Resume, profile, and preferences:

- `POST /upload-resume`
- `GET /profile`
- `POST /profile`
- `GET /application-profile`
- `POST /application-profile`
- `DELETE /application-profile`
- `GET /submission-settings`
- `POST /submission-settings`
- `DELETE /submission-settings`
- `POST /preferences`
- `POST /agent/resume-feedback`

Jobs and agent:

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
- `POST /applications/{app_id}/fill-review`
- `POST /applications/{app_id}/submit-readiness`
- `POST /applications/{app_id}/submit-confirmation`
- `GET /applications/{app_id}/fill-reviews`
- `GET /applications/{app_id}/automation-attempts`
- `DELETE /applications/{app_id}/fill-reviews`
- `POST /agent/prepare-application`
- `GET /applications/{app_id}/cover-letter.pdf`

Admin:

- `GET /admin/config`
- `PUT /admin/config`

## Agent Workflow

The LangGraph workflow is:

1. `parse_resume`
2. `search_jobs`
3. `analyze_fit`
4. `submit_application`
5. `apply_browser` only when `auto_apply=true` and qualifying jobs exist

The agent currently:

- extracts resume summary and skills
- searches job boards and target company career pages
- runs a conservative pre-screen that rejects only obvious non-fits before LLM analysis
- analyzes pass/maybe jobs in a batch LLM call
- persists job records incrementally, including review-only screened-out records with reasons
- selects jobs above the minimum match score
- optionally prepares supported application forms for review through Playwright

`GET /applications` also accepts `match_bucket=strong|below_threshold|screened_out|all`.
The dashboard uses `strong` by default so below-threshold and screened-out jobs stay out of
the main best-fit view while remaining reviewable from the full pipeline.

## Current Data Models

- `Resume`
- `JobPreference`
- `User`
- `Application`
- `Profile`
- `ScraperConfig`
- `PasswordResetToken`

## Known Backend Issues

- Authentication uses signed bearer tokens plus rotating refresh tokens, server-side session invalidation, refresh replay protection, and previous-secret verification for key rotation.
- The previous README contained a plaintext OpenRouter key. It has been removed; rotate the key if it was real.
- Database startup can run an Alembic baseline when `USE_ALEMBIC_MIGRATIONS=true`; local/dev still defaults to the lightweight `schema_migrations` runner.
- Core public write endpoints use Pydantic request schemas, and the main app/API responses now have explicit response models.
- Daily agent-run quotas are enforced for free/pro tiers, and browser fill-for-review is gated to pro/admin users.
- Agent runs are queued through FastAPI background tasks and persisted for polling.
- Browser automation has persisted audit records, and true final submit is hard-blocked by default with `ENABLE_TRUE_AUTO_SUBMIT=false`.
- Application answer-vault string fields are encrypted at rest with `APP_DATA_ENCRYPTION_KEY`; development falls back to the auth secret, but production requires the dedicated key.
- Fill-review screenshots and traces are served only through authenticated endpoints and pruned by `FILL_REVIEW_ARTIFACT_RETENTION_DAYS`.
- LLM calls are live by default and need test doubles for repeatable automated tests.

## Backend Implementation Priorities

1. Enable Alembic in staging, validate the baseline against an existing database, then retire the lightweight runner when production migration history is trusted.
2. Keep true final submit disabled by default until a real-submit pilot is explicitly approved.
3. Add export controls and deeper audit events for sensitive answer reads before production.

## Product Notes Preserved

The original goal remains:

Build an LLM-powered app that can analyze a user's resume, compare it to job postings, submit or prepare applications for the best matches, support enterprise and local LLM providers, offer subscription tiers, and show application history and status.

The current product expectation is that the user should not need separate "Analyze Resume" or "Save Preferences" actions before running the agent. The agent launch should save and analyze the required setup data as part of the workflow.
