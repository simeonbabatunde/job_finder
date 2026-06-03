# Job Finder Handoff

This is the persistent handoff record for Job Finder. Keep it current at the end of meaningful implementation sessions.

## Product Snapshot

- Product: Job Finder
- Current UI label in code: Job Finder
- Product promise: a smart career operations workspace that finds, scores, prepares, tracks, and optionally applies to matching jobs.
- Core audience: job seekers who want a repeatable application workflow with AI-assisted resume matching, tailored application materials, and application tracking.
- Reference UI direction: use the same calm, dense, research-dashboard language as the Influence Chart project.
- Security checklist: `docs/SECURITY_CHECKLIST.md`.

## Current Repository State

- Frontend lives in `frontend`.
- Backend lives in `backend`.
- Docker Compose runs frontend, backend, and Postgres.
- Frontend is Vite React with Tailwind CSS 4.
- Backend is FastAPI with SQLModel and LangGraph.
- The main workflow exists end to end:
  - auth/register/login
  - resume upload and parsing
  - profile save
  - preferences save
  - job search and fit analysis
  - application persistence
  - application package generation
  - application status update
  - cover letter PDF download
  - admin scraper configuration
- Documentation was expanded on 2026-05-31 with root docs, UI/UX direction, implementation plan, and this handoff.
- The first Influence Chart-style UI implementation pass is complete for the main dashboard, run panel, application history, package modal, auth modal, and admin settings.
- The matching workflow now runs a conservative pre-screen before full AI analysis, persists screened-out jobs with reasons, and keeps below-threshold/screened-out jobs in separate review lanes.
- Deployment health checks now cover API liveness, database reachability, and worker heartbeat freshness.

## Active Technical Direction

- Keep the current Vite/FastAPI stack for now.
- Port Influence Chart's visual system into this app rather than introducing a separate design framework.
- Use Tailwind plus a small local component layer.
- Use `lucide-react` for consistent icons.
- Keep the first screen as a real dashboard, not a hero or landing page.
- Prioritize user scoping, auth hardening, migrations, and tests before production deployment.

## UI/UX Target

Use these tokens from the Influence Chart project:

- Page: `#f6f8fb`
- Ink: `#172033`
- Muted: `#657084`
- Line: `#dce2ea`
- Soft: `#eef3f7`
- Accent: `#176b63`
- Accent soft: `#dff3ee`
- Positive: `#177245`

The app should feel like a calm career operations dashboard:

- top navigation
- compact workflow panels
- clear status chips
- scannable application table
- consistent field and button styles
- no decorative gradient blobs
- no nested page cards
- no emoji-led controls

Full direction is in `docs/UI_UX_DIRECTION.md`.
Auto-apply reliability, answer vault design, work authorization, and voluntary self-ID handling are in `docs/AUTO_APPLY_RELIABILITY_PLAN.md`.

## Current Code Risks

- Worktree was already dirty before this documentation pass. Do not assume non-doc changes were made by this session.
- The previous backend README contained a plaintext OpenRouter key. It has been removed from docs, but rotate it if it was real.
- Auth uses signed bearer tokens plus rotating refresh tokens stored in `localStorage`; server-side session records, logout invalidation, refresh replay protection, and previous-secret verification for key rotation are implemented.
- Resumes and preferences are now user-scoped in the touched backend flows.
- Database startup can run an Alembic current-schema baseline when `USE_ALEMBIC_MIGRATIONS=true`; local/dev still defaults to `create_all` plus the lightweight versioned `schema_migrations` runner.
- Core write endpoints use explicit Pydantic request schemas, and the main app/API responses now have explicit response models.
- Daily free/pro agent-run quotas are enforced server-side, and the UI shows remaining run quota.
- Browser fill-for-review is gated to pro/admin users; true auto-submit is hard-blocked by default with `ENABLE_TRUE_AUTO_SUBMIT=false`.
- Agent runs now support `AGENT_RUNNER_MODE=worker` with a Docker worker service that claims persisted queued runs; local default background mode is still available.
- Worker mode now writes heartbeat rows used by `/health/worker` to detect missing or stale workers before queued runs silently pile up.
- The main frontend surfaces now share the tokenized visual treatment. Remaining UI polish is incremental rather than a known split-style blocker.

## Session Start Checklist

- Read this file.
- Read `docs/IMPLEMENTATION_PLAN.md`.
- Read `docs/UI_UX_DIRECTION.md`.
- Check `git status --short`.
- Inspect any changed files before editing, especially because this repo currently has many modified and untracked files.
- Avoid reverting user changes.

## Session End Checklist

- Summarize completed work.
- Record files changed.
- Note tests/checks run.
- Note blockers or risks.
- Update the latest handoff entry below.

## Decision Log

| Date | Decision | Reason |
| --- | --- | --- |
| 2026-05-31 | Use Influence Chart design language for Job Finder | User requested a similar UI/UX design and color scheme. |
| 2026-05-31 | Document before code restyle | Worktree is already dirty, and a detailed plan/handoff was explicitly requested. |
| 2026-05-31 | Keep Tailwind primitives with a small local component layer | Matches Influence Chart and avoids premature dependency weight. |
| 2026-05-31 | Treat auth and user-scoping as production blockers | Current prototype auth and global latest resume/preferences can leak or mix user data. |
| 2026-05-31 | Backfill unowned resume/preference rows only for single-user local databases | Avoids guessing ownership in multi-user data while keeping the common local dev path smooth. |
| 2026-05-31 | Use signed bearer tokens before introducing external auth infrastructure | Removes the email-header trust model without adding a new dependency during this pass. |
| 2026-05-31 | Keep migrations lightweight for now | A versioned startup runner covers current local evolution without adding Alembic setup before tests exist. |
| 2026-06-02 | Use a conservative pre-screen before expensive matching work | Saves AI/package cost while keeping uncertain jobs eligible for full review. |
| 2026-06-03 | Keep true final submit behind an explicit pilot flag | Current flows are useful as fill-for-review, but real submission needs explicit approval, fixture coverage, auditability, and rollback. |
| 2026-06-03 | Add public non-sensitive health checks | Staging and Docker E2E need API, database, and worker readiness signals without exposing user data. |

## Open Questions

- Should the user-facing brand be "Job Finder", "Job Hunter", or another name?
- Should auth be custom JWT/session auth, Supabase Auth, Clerk, or another provider?
- Should true auto-submit ever submit without a final human confirmation per job? Current answer: no.
- Should sensitive voluntary self-identification answers be stored at all? Current answer: optional only, explicit consent required, encrypted at rest, default to decline/self-review.

## Latest Handoff Entry

Date: 2026-06-03

Completed:

- Verified the Docker Compose stack end to end: register, refresh token, save preferences/profile/application answers, save submission settings, upload resume, load user status, queue an agent run, retrieve the queued run, and logout.
- Verified the Alembic opt-in baseline with `alembic upgrade head` against a fresh temporary SQLite database in the uv Python 3.11 container.
- Added `app.time_utils.utc_now()` and replaced app-side `datetime.utcnow()` usage while preserving naive UTC storage compatibility.
- Added `ENABLE_TRUE_AUTO_SUBMIT=false` to `.env.example` and Docker Compose backend/worker environments.
- Added an explicit legacy `BrowserApplyService` guard that blocks `submit=True` unless `ENABLE_TRUE_AUTO_SUBMIT=true`.
- Added API-contract coverage proving browser final submit is blocked by default.
- Added `docs/SECURITY_CHECKLIST.md` covering private `.env` handling, key rotation, production auth secrets, artifact privacy, true-submit gating, and deployment checks.
- Added application answer-vault field encryption using `APP_DATA_ENCRYPTION_KEY`, with plaintext-backward-compatible reads and production startup enforcement for a dedicated key.
- Added fill-review screenshot/trace retention pruning through `FILL_REVIEW_ARTIFACT_RETENTION_DAYS` and suppressed artifact URLs when files are missing or expired.
- Added direct API-contract coverage for answer-vault encryption at rest and artifact retention pruning.
- Added `cryptography` as a direct backend dependency and refreshed `backend/uv.lock`.
- Added public health endpoints: `GET /health`, `GET /health/db`, and `GET /health/worker`.
- Added `WorkerHeartbeat` persistence, startup migration `0013_worker_heartbeat`, Alembic revision `0002_worker_heartbeat`, Docker heartbeat env vars, and worker loop heartbeat writes.
- Added deployment-readiness documentation covering health checks, staging env, worker readiness, migration mode, Docker E2E smoke, and production gates.
- Added `JobPreScreenService` with pass/maybe/reject buckets for cheap, high-recall screening before LLM fit analysis.
- Updated the agent search node to persist `Screened Out` jobs with reasons and send only pass/maybe jobs to the LLM analysis batch.
- Added `Application.pre_screen_status` and `Application.pre_screen_reasons` plus startup migration `0010_application_prescreen`.
- Added `GET /applications?match_bucket=strong|below_threshold|screened_out|all`.
- Added server-side action guards so package generation and fill-for-review are blocked for screened-out jobs and jobs below the latest minimum match score.
- Updated the dashboard to default to strong matches, add full-page lanes for below-threshold and screened-out jobs, show pre-screen reasons, and disable package/fill actions for non-qualifying rows.
- Updated backend and auto-apply reliability docs with the pre-screen cost gate and match bucket behavior.
- Reviewed current frontend structure, backend structure, agent workflow, models, services, and existing docs.
- Reviewed the Influence Chart project for the target design language and docs style.
- Added root `README.md`.
- Added `docs/UI_UX_DIRECTION.md`.
- Added `docs/IMPLEMENTATION_PLAN.md`.
- Added `docs/HANDOFF.md`.
- Added `docs/AUTO_APPLY_RELIABILITY_PLAN.md`.
- Rewrote `frontend/README.md`.
- Rewrote `backend/README.md`.
- Removed a plaintext OpenRouter key from the backend README rewrite. Rotate the key if it was real.
- Added root `.gitignore`.
- Added `.env.example`.
- Installed `lucide-react`.
- Added Influence Chart-style CSS variables to `frontend/src/index.css`.
- Removed Vite template styling from `frontend/src/App.css`.
- Added shared UI primitives in `frontend/src/components/ui.tsx`.
- Added `frontend/src/components/AppHeader.tsx`.
- Reworked `frontend/src/App.tsx` into a product dashboard shell with a compact overview strip, consolidated setup workflow, search assistant panel, recent matches, and full `/applications` route.
- Restyled `ResumeUpload`, `JobPreferences`, `UserProfile`, `AgentControls`, `AgentDashboard`, `ApplicationPackageModal`, `Login`, and `AdminPanel`.
- Added a full generated-package Markdown download from `ApplicationPackageModal`, alongside the existing cover-letter PDF download.
- Refined key app copy to frame Job Finder as a smart job search assistant that matches roles to the user's resume/preferences and packages application materials.
- Added typed frontend API payloads for user status, profile, preferences, resume status, and auth user shape.
- Moved `cn` into `frontend/src/lib/cn.ts` so Fast Refresh no longer warns about non-component exports from the UI component module.
- Removed remaining explicit `any` lint violations in the touched frontend flow.
- Removed the standalone setup readiness card; readiness now appears in the compact dashboard overview strip and in each workflow section.
- Restored the two-column dashboard layout with Workspace Setup on the left and Run Agent/Matched Jobs on the right. The setup panel uses compact section headers instead of a left label rail, and the right-rail Matched Jobs view uses compact rows instead of a wide table to avoid signed-in overflow.
- Restyled the remaining legacy utility surfaces: `ResumeFeedback`, `ResetPassword`, `OAuthCallback`, `JobSearch`, and `ProfileSettings`.
- Added `containerClassName` support to the shared `TextField` wrapper for grid alignment.
- Added `user_id` ownership to `Resume` and `JobPreference`.
- Added a versioned startup migration that adds missing ownership columns and backfills only when the database has exactly one user.
- Scoped resume and preference lookups for upload, preferences save, user status, agent run, single-job analysis, application packages, and resume feedback.
- Added `GET /applications` query parameters for `limit`, `sort`, `direction`, and `status`.
- Updated the dashboard application table to request the limited recent view through the API.
- Fixed Google and LinkedIn callback profile creation by including a default location value.
- Replaced `X-User-Email` auth with signed bearer tokens on protected backend endpoints.
- Updated login, registration, legacy social auth, and OAuth callbacks to issue access tokens.
- Updated frontend auth storage to keep `auth_token` and send `Authorization: Bearer ...`.
- Added server-side auth session records, token IDs, logout invalidation, frontend logout revocation, and API coverage proving revoked tokens are rejected.
- Added rotating refresh tokens, refresh replay protection, previous auth-secret verification, production weak-secret checks, and frontend refresh-on-status recovery.
- Added `APP_ENV`, `AUTH_SECRET_KEY`, `AUTH_PREVIOUS_SECRET_KEYS`, `AUTH_ACCESS_TOKEN_TTL_SECONDS`, and `AUTH_REFRESH_TOKEN_TTL_SECONDS` to `.env.example`.
- Added `backend/app/schemas.py` with explicit request schemas for auth, profile, preferences, single-job analysis, application package generation, application status, and password reset flows.
- Replaced the touched broad `dict` request payloads in `backend/app/api/endpoints.py`.
- Added explicit response schemas for auth, profile, preferences, agent run, application history, single-job analysis, application package generation, application status, resume feedback, and password reset flows.
- Updated application history responses to omit persistence-only `user_id`.
- Replaced the one-off startup compatibility patch with a lightweight `schema_migrations` runner in `backend/app/database.py`.
- Added Alembic scaffolding, a current-schema baseline revision, and an opt-in startup path through `USE_ALEMBIC_MIGRATIONS=true`.
- Repaired `backend/.venv` with Python 3.14 and installed backend dependencies plus `pytest`.
- Added `backend/app/tests/test_api_contracts.py` covering bearer auth, user-scoped resume/preferences, migration recording, application sorting/filtering/limit behavior, persisted agent runs, quota enforcement, and pro/admin browser fill-for-review gating.
- Added `AgentRun` and `AutoApplyAudit` persistence models.
- Added agent run history endpoints: `GET /agent/runs` and `GET /agent/runs/{run_id}`.
- Changed `POST /agent/run` to queue background work and return an `agent_run_id`.
- Added daily free/pro agent-run quota enforcement with `FREE_DAILY_AGENT_RUN_LIMIT` and `PRO_DAILY_AGENT_RUN_LIMIT`.
- Gated browser fill-for-review to pro/admin users and surfaced quota status through `/user/status`.
- Updated the Run Agent panel to show remaining run quota, disable browser fill-for-review for free users, and poll run status.
- Added application link-resolution metadata, migration support, and `ApplicationLinkResolver` classification for ATS, aggregator, company, and unknown links.
- Added `POST /applications/{app_id}/resolve-link` with conservative Playwright resolution for aggregator links.
- Updated the dashboard application cards/table to show link readiness, resolve unresolved links, and open the resolved employer URL when available.
- Guarded the auto-apply node so unresolved aggregator/company/unknown links are held for review and only resolved supported ATS links can proceed to browser automation.
- Added `ApplicationAnswerProfile`, the `GET/POST /application-profile` answer vault API, and `/user/status` preload support.
- Added the dashboard `Application answers` section for work authorization, sponsorship, relocation/work-setting preferences, compensation/start timing, and optional self-identification answers.
- Added backend consent handling so sensitive self-ID values are saved as `prefer_not_to_answer` unless demographic storage consent is enabled.
- Added `DELETE /application-profile` and a dashboard reset action for clearing saved application answers.
- Added the first deterministic fill-for-review endpoint, `POST /applications/{app_id}/fill-review`, for resolved Greenhouse, Lever, Ashby, SmartRecruiters, Workday, BambooHR, iCIMS, Recruitee, and Taleo applications.
- Added `ApplicationFillReviewService` to fill standard supported-ATS fields, upload the saved resume, use consented answer-vault fields where possible, and stop before submit.
- Added dashboard `Fill review` actions and a review summary modal for filled fields, missing fields, blockers, and the application URL.
- Added `ApplicationFillReview` persistence and `GET /applications/{app_id}/fill-reviews` so fill-review attempts are auditable per application.
- Updated the fill-review modal to show recent saved review attempts after a run.
- Added `DELETE /applications/{app_id}/fill-reviews` and a modal clear action for saved fill-review attempts.
- Added ephemeral screenshot preview support in fill-review responses and the review modal.
- Added persisted fill-review screenshot and Playwright trace artifacts, authenticated artifact endpoints, migration support, and dashboard actions to preview saved screenshots or download traces.
- Added durable worker-mode agent execution with `claimed_at` queue metadata, stale-run protection, `backend/app/worker.py`, Docker Compose worker service wiring, and worker-mode API contract coverage.
- Added final-submit guardrail settings, allow/deny lists, readiness evaluation, dashboard guardrail controls, and a fill-review modal readiness check. This still does not submit applications.
- Added no-click final confirmation via `POST /applications/{app_id}/submit-confirmation`, fixture-backed submit-control detection, audit logging, and a dashboard final-step inspection action.
- Added persisted `AutoApplyAttempt` records, `GET /applications/{app_id}/automation-attempts`, attempt-linked audit events, and a dashboard automation timeline tying fill-review and final confirmation into one workflow.
- Added step-level telemetry to `AutoApplyAttempt` records for fill-review and final-confirmation transitions, including `attempt_created`, `inputs_validated`, `browser_fill_started`, `fill_review_completed`, `readiness_checked`, `submit_control_detection`, and `final_confirmation_prepared`.
- Updated the dashboard automation timeline to show the latest attempt steps inside each attempt card.
- Added guarded Workday fill-for-review and no-click submit-control detection support.
- Added fixture-backed Workday submit detection coverage for a ready form and an account/sign-in gate.
- Added guarded BambooHR fill-for-review support and fixture-backed no-click submit-control detection.
- Added guarded iCIMS fill-for-review support and fixture-backed no-click submit-control detection.
- Added guarded Recruitee and Taleo fill-for-review support and fixture-backed no-click submit-control detection.
- Added focused API coverage for successful application package generation, package cover-letter persistence, admin scraper-config access/update, and graceful job-search scraper failures.

Tests/checks:

- `npm run build` in `frontend` passed.
- `npm run lint` in `frontend` passed.
- `PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/app/tests` passed with 33 tests after answer-vault encryption and artifact retention.
- Docker Compose E2E smoke passed against `http://127.0.0.1:8000` and `http://localhost:5173`.
- Alembic `upgrade head` passed in an isolated uv Python 3.11 container against a temporary SQLite database.
- Backend syntax compile check passed for `models.py`, `database.py`, `schemas.py`, `endpoints.py`, `state.py`, `nodes.py`, `job_pre_screen.py`, and `persistence.py`.
- Alembic baseline upgrade was verified in the uv Python 3.11 container against a temporary SQLite database.
- `git diff --check` passed.
- `docker compose config` rendered successfully.
- `npm audit --json` in `frontend` reports 0 vulnerabilities after `npm audit fix`.

Next concrete step:

- Add export/delete controls and deeper audit events for sensitive answer-vault reads before production, then run a staging rehearsal with `USE_ALEMBIC_MIGRATIONS=true` using `docs/DEPLOYMENT_READINESS.md`.
