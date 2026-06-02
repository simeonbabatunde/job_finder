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
AUTH_TOKEN_TTL_SECONDS=604800
FREE_DAILY_AGENT_RUN_LIMIT=3
PRO_DAILY_AGENT_RUN_LIMIT=50
FILL_REVIEW_ARTIFACT_DIR=storage/fill_review_artifacts
AGENT_RUNNER_MODE=background
AGENT_WORKER_POLL_SECONDS=2
AGENT_RUN_STALE_MINUTES=120
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
- `GET /applications/{app_id}/fill-reviews`
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
- analyzes jobs in a batch LLM call
- persists job records incrementally
- selects jobs above the minimum match score
- optionally fills or submits application forms through Playwright

## Current Data Models

- `Resume`
- `JobPreference`
- `User`
- `Application`
- `Profile`
- `ScraperConfig`
- `PasswordResetToken`

## Known Backend Issues

- Authentication uses signed bearer tokens stored by the frontend. Move to hardened sessions/JWT infrastructure before production.
- The previous README contained a plaintext OpenRouter key. It has been removed; rotate the key if it was real.
- Database startup uses `SQLModel.metadata.create_all` plus a lightweight `schema_migrations` table. Alembic is still a future production upgrade.
- Core public write endpoints use Pydantic request schemas, and the main app/API responses now have explicit response models.
- Daily agent-run quotas are enforced for free/pro tiers, and auto-submit is gated to pro/admin users.
- Agent runs are queued through FastAPI background tasks and persisted for polling.
- Browser auto-apply has persisted audit records, but still needs stronger confirmation rules and safer production constraints.
- LLM calls are live by default and need test doubles for repeatable automated tests.

## Backend Implementation Priorities

1. Harden auth secrets and add refresh-token rotation if longer-lived sessions are needed.
2. Move background agent execution to a durable worker/queue for multi-process deployments.
3. Move schema management to Alembic if the app needs a larger production migration workflow.
4. Add stronger browser auto-submit confirmation and allow/deny rules.
5. Expand pytest coverage for package generation, admin access, and external-service failure paths.

## Product Notes Preserved

The original goal remains:

Build an LLM-powered app that can analyze a user's resume, compare it to job postings, submit or prepare applications for the best matches, support enterprise and local LLM providers, offer subscription tiers, and show application history and status.

The current product expectation is that the user should not need separate "Analyze Resume" or "Save Preferences" actions before running the agent. The agent launch should save and analyze the required setup data as part of the workflow.
