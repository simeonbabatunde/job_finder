# Job Finder

Job Finder is a smart job search assistant that helps remove the repetitive parts of job hunting. A user uploads a resume, sets preferences and profile details, then the assistant searches for aligned roles, scores fit, tracks the pipeline, and packages application materials for each match.

## Current Stack

- Frontend: React 19, TypeScript, Vite, Tailwind CSS 4
- Backend: FastAPI, SQLModel, PostgreSQL, LangGraph, LangChain
- Job discovery: python-jobspy plus custom scrapers
- LLM providers: OpenAI, OpenRouter, Gemini, and Ollama through `backend/app/agent/llm_factory.py`, selected by `LLM_PROVIDER` and model override env vars
- Browser automation: Playwright for supported-ATS fill-for-review; true submit is disabled by default
- Local orchestration: Docker Compose
- Python dependency manager: uv through `backend/pyproject.toml` and `backend/uv.lock`

## Product Shape

The current app already supports the main workflow:

1. Sign in or register.
2. Upload a resume.
3. Fill a personal profile for application forms and cover letters.
4. Set job preferences and target companies.
5. Run the search assistant to search, score, and prepare supported applications for review.
6. Review best-fit jobs and application status.
7. Generate a cover letter, tailored summary, Q&A answers, interview prep, and company brief for a selected job.

## Design Direction

The next UI pass should follow the same practical, research-dashboard design language used in the Influence Chart project:

- Light operational surface: `#f6f8fb`
- Primary ink: `#172033`
- Muted text: `#657084`
- Borders: `#dce2ea`
- Soft fill: `#eef3f7`
- Accent: `#176b63`
- Accent soft: `#dff3ee`
- Positive state: `#177245`

That means the Job Finder interface should feel like a focused career operations dashboard: dense, calm, scannable, and useful immediately. Avoid decorative gradient orbs, oversized hero treatment, nested cards, and emoji-led controls.

Detailed UI direction is in [docs/UI_UX_DIRECTION.md](./docs/UI_UX_DIRECTION.md).

## Project Docs

- [Implementation Plan](./docs/IMPLEMENTATION_PLAN.md)
- [UI/UX Direction](./docs/UI_UX_DIRECTION.md)
- [Auto-Apply Reliability Plan](./docs/AUTO_APPLY_RELIABILITY_PLAN.md)
- [Security Checklist](./docs/SECURITY_CHECKLIST.md)
- [Deployment Readiness](./docs/DEPLOYMENT_READINESS.md)
- [Manual QA Checklist](./docs/MANUAL_QA_CHECKLIST.md)
- [Handoff](./docs/HANDOFF.md)
- [Frontend README](./frontend/README.md)
- [Backend README](./backend/README.md)

## Local Development

Recommended full stack:

```bash
docker compose up --build
```

Full launch-readiness preflight:

```bash
./scripts/preflight.sh
```

The preflight command runs the Dockerized backend test suite, frontend
lint/build, Compose config rendering, an isolated Alembic upgrade, Docker health
checks, answer-vault export/audit smoke, and a browser dashboard smoke. It starts the local Compose
stack and leaves it running so you can continue testing in the browser. To make
the command clean up containers and volumes when it exits, run:

```bash
PREFLIGHT_COMPOSE_DOWN_ON_EXIT=1 ./scripts/preflight.sh
```

Frontend only:

```bash
cd frontend
npm install
npm run dev
```

Backend only:

```bash
cd backend
uv sync
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Default URLs:

- Frontend: `http://localhost:5173`
- Backend: `http://localhost:8000`
- Postgres: `localhost:5432`

## Important Current Risks

- Auth uses signed bearer tokens plus rotating refresh tokens, server-side session invalidation, refresh replay protection, and previous-secret verification for key rotation.
- Resume and preferences are scoped to the active user in the core backend flows.
- Database startup can run an Alembic baseline when `USE_ALEMBIC_MIGRATIONS=true`; local/dev still defaults to the lightweight versioned migration table.
- The previous backend README contained a plaintext OpenRouter key. It has been removed from docs, but the key should be rotated if it was real.
- Daily agent-run quotas, pro/admin fill-for-review gating, persisted agent run logs, and auto-apply audit records are implemented.
- Agent runs, worker claims, browser fill-review, submit-readiness, and submit-confirmation now emit structured JSON operational events without answer/resume contents.
- True final submit is hard-blocked by default with `ENABLE_TRUE_AUTO_SUBMIT=false`; readiness settings can only be armed for approved pilot users/ATS types.
- Application answer-vault string fields are encrypted before persistence; production requires `APP_DATA_ENCRYPTION_KEY`.
- Application answer-vault reads, exports, resets, and automation use are audited without storing answer values in the audit log.
- Answer-vault data-key rotation has a dry-run/apply re-encryption job before old keys are removed.
- Signed-in users can export account data, including resumes, preferences, generated package records, application history, and automation artifact links.
- Production-like startup rejects weak secrets, missing answer-vault encryption keys, wildcard CORS, and localhost CORS origins.
- Fill-review screenshots and traces are authenticated artifacts with `FILL_REVIEW_ARTIFACT_RETENTION_DAYS` pruning.
- Public health checks now cover API liveness, DB reachability, and worker heartbeat freshness through `/health`, `/health/db`, and `/health/worker`.
- The focused backend test suite now covers auth, ownership, migrations, application queries, quotas, agent run persistence, LLM provider configuration, and structured errors.
- `./scripts/preflight.sh` is the repeatable local/CI gate before staging or larger feature work, including a signed-in browser smoke for the dashboard shell.

See [docs/IMPLEMENTATION_PLAN.md](./docs/IMPLEMENTATION_PLAN.md) for the staged fix plan.
See [docs/OPERATIONS_RUNBOOK.md](./docs/OPERATIONS_RUNBOOK.md) for staging, backup/restore, account export, and answer-vault key rotation procedures.
