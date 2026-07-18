# JobMatchKit

JobMatchKit is a smart job search assistant that helps remove the repetitive parts of job hunting. A user can save one or more matching profiles, each with its own resume and job-search strategy, then the assistant searches for aligned roles, scores fit, tracks the pipeline, and packages application materials for each match.

Repository: `https://github.com/simeonbabatunde/jobmatchkit`

## Current Stack

- Frontend: React 19, TypeScript, Vite, Tailwind CSS 4
- Backend: FastAPI, SQLModel, PostgreSQL, LangGraph, LangChain
- Job discovery: official company/ATS sources first, ranked large-company career exploration, then python-jobspy/custom scrapers as fallback discovery hints
- LLM providers: OpenAI, OpenRouter, Gemini, and Ollama through `backend/app/agent/llm_factory.py`, selected by `LLM_PROVIDER` and model override env vars
- Application packaging: server-generated ZIP/PDF materials for review before applying on employer sites
- Billing: Stripe Checkout for the $10/month Pro upgrade, Stripe Customer Portal for subscription management, and Stripe webhooks as the source of truth
- Local orchestration: Docker Compose
- Python dependency manager: uv through `backend/pyproject.toml` and `backend/uv.lock`

## Product Shape

The current app already supports the main workflow:

1. Sign in or register.
2. Create or select a saved matching profile.
3. Attach a resume to that profile.
4. Fill a personal profile for generated materials.
5. Set profile-specific target roles, locations, companies, match score, and recency.
6. Run the search assistant with the selected matching profile to search, score, and save strong matches.
7. Review best-fit jobs and application status by profile.
8. Generate and download a ZIP package with cover letter, resume-improvement checklist, Q&A answers, interview prep, and company brief for a selected job.
9. Open the employer application link manually when ready to apply.
10. Upgrade to Pro through Stripe Checkout, then manage billing through the Stripe Customer Portal.

## Design Direction

The UI follows the same practical, research-dashboard design language used in the Influence Chart project:

- Light operational surface: `#f6f8fb`
- Primary ink: `#172033`
- Muted text: `#657084`
- Borders: `#dce2ea`
- Soft fill: `#eef3f7`
- Accent: `#3658a8`
- Accent hover: `#2a4585`
- Accent soft: `#e8edfb`
- Positive state: `#3f6fb5`

That means the JobMatchKit interface should feel like a focused career operations dashboard: dense, calm, scannable, and useful immediately. Avoid decorative gradient orbs, oversized hero treatment, nested cards, and emoji-led controls.

Detailed UI direction is in [docs/UI_UX_DIRECTION.md](./docs/UI_UX_DIRECTION.md).

## Saved Matching Profiles

Saved matching profiles let a user run separate job-search tracks without overwriting their setup. Each profile has a name, one selected resume, target roles, locations, job types, target companies, minimum match score, and recency window. The account-level contact profile and reusable application answers stay global.

Examples:

- `Embedded Firmware`: embedded/firmware resume, hardware companies, higher minimum score.
- `Backend Platform`: backend resume, platform roles, cloud/software companies.
- `Technical Program Manager`: TPM resume, program/product operations targets.

Implementation contract:

- New users and existing users always have a default matching profile.
- Existing latest-resume/latest-preferences behavior is preserved through that default profile.
- Matching runs store the selected `matching_profile_id` and `resume_id` so historical runs are auditable.
- Saved applications are tagged with the profile/run that produced them so the pipeline can be filtered by job-search track.

## Matching Sources

JobMatchKit searches allowed companies first, then ranked large-company official career sources, then job boards only if more candidates are needed. The Fortune 500 phase runs before the 501-1000 tail; if the official-source target is met, job-board scraping is skipped for that run.

The bundled `backend/app/data/company_rankings/fortune_us_seed.csv` is a practical seed file, not a licensed canonical Fortune dataset. For production, set `FORTUNE_COMPANY_RANKING_CSV` to a fuller maintained CSV with columns `rank,company,sector,role_tags,aliases`, then tune `FORTUNE_COMPANIES_PER_PHASE`, `FORTUNE_MIN_CANDIDATE_JOBS`, `MAX_TARGET_ROLE_SEARCH_TERMS`, `RELEVANT_OFFICIAL_COMPANIES_MAX`, and board-link resolution limits for crawl breadth.

## Project Docs

- [Implementation Plan](./docs/IMPLEMENTATION_PLAN.md)
- [UI/UX Direction](./docs/UI_UX_DIRECTION.md)
- [Auto-Apply Reliability Plan](./docs/AUTO_APPLY_RELIABILITY_PLAN.md)
- [Security Checklist](./docs/SECURITY_CHECKLIST.md)
- [Deployment Readiness](./docs/DEPLOYMENT_READINESS.md)
- [VPS Deployment Guide](./docs/VPS_DEPLOYMENT.md)
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

New local installs use `POSTGRES_DB=jobmatchkit`. If you already have an older
local Docker database from before the JobMatchKit rebrand, back it up before
changing `POSTGRES_DB`, `DATABASE_URL`, `COMPOSE_PROJECT_NAME`, or the root
folder name; those values affect which Compose volume/database Docker uses.

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

## Browser Automation Retired

`Apply with assistant` and `Application Prep` have been removed from the product. The app now focuses on reliable job discovery, fit scoring, pipeline tracking, and downloadable application packages. Users open employer application links manually from the pipeline.

## Important Current Risks

- Auth uses signed bearer tokens plus rotating refresh tokens, server-side session invalidation, refresh replay protection, and previous-secret verification for key rotation.
- Resume and preferences are scoped to the active user in the core backend flows.
- Database startup can run an Alembic baseline when `USE_ALEMBIC_MIGRATIONS=true`; local/dev still defaults to the lightweight versioned migration table.
- The previous backend README contained a plaintext OpenRouter key. It has been removed from docs, but the key should be rotated if it was real.
- Daily matching-run quotas, persisted matching run logs, and downloadable generated packages are implemented.
- Matching runs and worker claims emit structured JSON operational events without answer/resume contents.
- Application answer-vault string fields are encrypted before persistence; production requires `APP_DATA_ENCRYPTION_KEY`.
- Application answer-vault reads, exports, and resets are audited without storing answer values in the audit log.
- Answer-vault data-key rotation has a dry-run/apply re-encryption job before old keys are removed.
- Signed-in users can export account data, including resumes, preferences, generated package records, and application history.
- Production-like startup rejects weak secrets, missing answer-vault encryption keys, wildcard CORS, and localhost CORS origins.
- Public health checks now cover API liveness, DB reachability, and worker heartbeat freshness through `/health`, `/health/db`, and `/health/worker`.
- The focused backend test suite now covers auth, ownership, migrations, application queries, quotas, matching run persistence, LLM provider configuration, and structured errors.
- `./scripts/preflight.sh` is the repeatable local/CI gate before staging or larger feature work, including a signed-in browser smoke for the dashboard shell.

See [docs/IMPLEMENTATION_PLAN.md](./docs/IMPLEMENTATION_PLAN.md) for the staged fix plan.
See [docs/OPERATIONS_RUNBOOK.md](./docs/OPERATIONS_RUNBOOK.md) for staging, backup/restore, account export, and answer-vault key rotation procedures.
