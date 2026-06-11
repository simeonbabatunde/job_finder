# JobMatchHero Implementation Plan

This plan is based on a code review of the current repository on 2026-05-31 and the Influence Chart UI/UX reference project.

## Status Legend

- `Not started`: no implementation work has begun.
- `Next`: the next implementation stage to start.
- `In progress`: active implementation exists but is incomplete.
- `Done`: implemented and verified.
- `Blocked`: waiting on a decision, credential, dependency, or external service.

## Current Code Analysis

### Frontend

The frontend is a Vite React app in `frontend/`.

Key files:

- `src/App.tsx`: manual route switching, top-level layout, auth state, resume/preferences/profile loading, and the main workflow.
- `src/components/ResumeUpload.tsx`: drag/drop upload, stored resume display, extracted skills, summary.
- `src/components/ResumeFeedback.tsx`: AI resume review panel.
- `src/components/UserProfile.tsx`: application profile fields and completeness banner.
- `src/components/JobPreferences.tsx`: target roles, location, experience, job type, target companies, match score, recency.
- `src/components/AgentControls.tsx`: validates resume/preferences, uploads and saves silently, starts the search workflow.
- `src/components/AgentDashboard.tsx`: application table, sorting, inline "view all", clear history, package modal trigger.
- `src/components/ApplicationPackageModal.tsx`: cover letter, summary, talking points, Q&A, interview prep, company brief, PDF download, status updates.
- `src/components/Login.tsx`: login, register, and forgot password modal.
- `src/components/AdminPanel.tsx`: scraper board configuration.
- `src/api/client.ts`: API wrapper functions.

Strengths:

- The main product loop already exists end to end.
- Components are mostly small and easy to extract into a shared design layer.
- The application package modal is feature-rich and valuable.
- The dashboard has useful state surfaces: resume skills, resume summary, profile completeness, application statuses, and fit scores.

Resolved and residual notes:

- The main UI has been moved onto the JobMatchHero token system with a dashboard-first shell.
- `src/App.css` previously contained Vite template styles; those have been replaced with a minimal note.
- Shared UI primitives now cover the app shell, panels, headers, buttons, chips, progress bars, fields, and empty states.
- Manual routing in `App.tsx` will get brittle as pages grow.
- Applications now have a real `/applications` route.
- Auth uses signed bearer tokens and rotating refresh tokens stored in `localStorage`; server-side invalidation, refresh replay protection, and previous-secret verification for key rotation are implemented.
- Frontend state uses `any` in several places, which hides API contract drift.

### Backend

The backend is a FastAPI app in `backend/`.

Key files:

- `main.py`: FastAPI app, CORS, DB table creation, router mount.
- `app/api/endpoints.py`: auth, OAuth callbacks, resume upload, preferences, profile, matching run, applications, admin config, password reset, application package, status update, resume feedback.
- `app/models.py`: SQLModel tables for resumes, preferences, users, applications, profiles, scraper config, reset tokens.
- `app/agent/graph.py`: LangGraph workflow.
- `app/agent/nodes.py`: resume parsing, job search, fit analysis, submission selection, browser application.
- `app/agent/llm_factory.py`: OpenAI, OpenRouter, Gemini, Ollama factory.
- `app/services/job_search.py`: JobSpy plus custom scraper config.
- `app/services/persistence.py`: application upsert and dedupe.
- `app/services/browser_apply.py`: Playwright form fill and optional submission.
- `app/services/resume_parser.py`: resume text extraction.
- `app/services/ats_scraper.py` and `app/services/motion_recruitment.py`: custom discovery paths.

Strengths:

- The matching workflow is cleanly separated into LangGraph nodes.
- LLM provider selection is centralized.
- Application persistence includes useful URL and title/company dedupe.
- The application package endpoint already produces high-value artifacts.
- Admin scraper configuration exists.

Resolved and residual notes:

- Resume and preferences are now user-scoped in the core backend flows.
- Auth now uses signed bearer tokens with server-side session records, logout invalidation, rotating refresh tokens, replay protection, and previous-secret verification for key rotation.
- Startup can run an Alembic baseline when `USE_ALEMBIC_MIGRATIONS=true`; local/dev still defaults to `create_all` plus the lightweight `schema_migrations` table.
- Core public API request and response schemas are explicit for the main app flows.
- Daily free/pro run quotas are enforced server-side.
- Matching runs are persisted as queued records, can run in local background mode, and can be processed by the Docker worker service in worker mode.
- Browser fill-for-review is gated to pro/admin users; true final submit is hard-blocked by default with `ENABLE_TRUE_AUTO_SUBMIT=false`, and future readiness settings require an approved pilot user/admin plus optional ATS allowlisting.
- Auto-apply reliability, ATS adapters, hard stop rules, work authorization, and voluntary self-ID handling are documented in `docs/AUTO_APPLY_RELIABILITY_PLAN.md`.
- The application answer vault foundation is implemented with `ApplicationAnswerProfile`, `GET/POST /application-profile`, and a dashboard `Application answers` section.
- Fill-for-review adapters are implemented for resolved Greenhouse, Lever, Ashby, SmartRecruiters, Workday, BambooHR, iCIMS, Recruitee, and Taleo links via `POST /applications/{app_id}/fill-review`.
- Fill-review attempts are now saved as application-scoped history through `ApplicationFillReview` and `GET /applications/{app_id}/fill-reviews`.
- Fill-review screenshots and Playwright traces are persisted as authenticated local artifacts and surfaced from saved review history.
- Final-submit guardrails are implemented with user-scoped submission settings, per-application readiness checks, a no-click final confirmation endpoint with fixture-backed submit-control detection, and persisted `AutoApplyAttempt` records tying fill-review and confirmation into one auditable workflow. Attempts now include compact step-level telemetry for fill-review and final-confirmation transitions. Actual final submission remains disabled.
- A focused backend test suite now covers auth, ownership, migrations, application queries, quotas, matching run persistence, LLM provider configuration, and structured errors.

## Milestone 0: Repository Hygiene and Documentation

Status: Done

Goal:

Make the project understandable and safe to continue from.

Deliverables:

- Root `README.md`.
- Frontend README rewritten from the Vite template.
- Backend README rewritten from loose notes.
- `docs/HANDOFF.md`.
- `docs/IMPLEMENTATION_PLAN.md`.
- `docs/UI_UX_DIRECTION.md`.
- `docs/AUTO_APPLY_RELIABILITY_PLAN.md`.
- Root `.gitignore`.
- `.env.example` covering frontend, backend, and Docker Compose values.

Acceptance criteria:

- A maintainer can understand the app, current risks, UI direction, and deployment gates from docs alone.
- Generated files such as `__pycache__`, `.env`, `node_modules`, and build output are ignored.

Implementation notes:

- Added root `.gitignore` and `.env.example`.
- Added `docs/AUTO_APPLY_RELIABILITY_PLAN.md` for the reliability path before production auto-submit.
- User-facing brand and new local database defaults are standardized as "JobMatchHero"/`jobmatchhero`; legacy local installs may still have pre-rebrand local data until migrated.

## Milestone 1: Design System Foundation

Status: Done

Goal:

Port the Influence Chart visual language into the Vite React app.

Deliverables:

- CSS variables in `frontend/src/index.css` for page, ink, muted, line, soft, accent, accent-soft, positive, warning, and danger.
- Removal of unused Vite template styles from `frontend/src/App.css`.
- Shared components:
  - `AppHeader`
  - `PageShell`
  - `SectionHeader`
  - `Button`
  - `IconButton`
  - `Field`
  - `StatusChip`
  - `DataTable`
  - `EmptyState`
  - `ProgressBar`
- `lucide-react` dependency for consistent icons.
- First pass implemented with `src/components/ui.tsx`, `src/components/AppHeader.tsx`, tokenized `src/index.css`, cleaned `src/App.css`, and `lucide-react`.

Acceptance criteria:

- No one-off indigo/violet gradients remain in the main dashboard workflow.
- Buttons, fields, status chips, empty states, tables, and section headers use shared patterns.
- UI elements stay readable and stable on mobile and desktop.

Implementation notes:

- Keep Tailwind primitives. Do not introduce a heavy component library.
- Prefer simple composition over abstraction until at least two components share a pattern.
- Use `rounded-lg` for cards and panels.
- Remaining utility surfaces have been tokenized enough for the current UI pass; future changes should be driven by specific usability issues rather than broad restyling.

## Milestone 2: App Shell and Navigation

Status: Done

Goal:

Replace the single centered hero card with a product shell that matches the Influence Chart header and page layout.

Deliverables:

- Header with brand, navigation, plan chip, email, admin link when permitted, and sign out.
- Dashboard route as the default view.
- Applications route for full history.
- Admin route inside the same visual shell.
- Reset password and OAuth callback remain standalone utility routes but use shared tokens.

Acceptance criteria:

- The first screen is immediately usable.
- The app no longer presents as a marketing hero.
- Users can navigate to application history without expanding a table inline.

Implementation notes:

- Added `AppHeader` and a full `/applications` branch using the shared application table.
- The app still uses manual route branching in `App.tsx`; introduce a router when page count grows.

Implementation notes:

- React Router can be added, or the existing manual routing can be extracted into a tiny route switch first.
- Avoid a landing page unless there is a separate marketing requirement later.

## Milestone 3: Main Dashboard Redesign

Status: Done

Goal:

Make resume, profile, preferences, search runs, and recent applications feel like one operational workflow.

Deliverables:

- Compact dashboard overview strip for resume, profile, preference, and quota readiness.
- Consolidated Workspace Setup panel with Resume, Preferences, and Profile sections separated by dividers.
- Resume section using shared upload and status styles.
- Profile section using shared fields and completion chip.
- Preferences section with compact controls.
- Right-rail search assistant panel with clear fill-for-review state and risk language.
- Right-rail recent applications list limited to 5 rows, with the full table kept on the Applications page.

Acceptance criteria:

- A signed-in user can understand readiness at a glance.
- Resume/Profile/Preferences have visible completion states.
- The "Start matching" action saves the required setup data as it does today.
- Recent applications are visible without dominating the page.

Implementation notes:

- Dashboard shell, compact overview strip, consolidated setup workflow, right-rail search assistant panel, and compact recent matches were restyled in the UI pass.
- The current refs-based save/upload flow remains acceptable for the compact dashboard scope; revisit only if the workflow becomes multi-step or harder to reason about.

## Milestone 4: Application Pipeline and History

Status: Done

Goal:

Turn matched jobs into a dependable application pipeline.

Deliverables:

- Dedicated `/applications` page.
- Table with columns: Role, Company, Fit, Status, Date, Actions.
- Status filters and sort controls.
- Status chip system:
  - Identified
  - Analyzed
  - Analysis Failed
  - Applied
  - Phone Screen
  - Interview
  - Take-Home
  - Offer
  - Rejected
  - No Response
- Row action to open the application package modal.
- Clear history moved behind a safer confirm flow.

Acceptance criteria:

- Dashboard shows 5 recent applications.
- Full page shows the complete history.
- Sorting and filtering work without layout shift.
- Status changes update the current row without a full reload.

Implementation notes:

- Backend now supports `/applications` query parameters for `limit`, `sort`, `direction`, and `status`.
- Dashboard requests the recent limited view; the full `/applications` view requests the complete history.
- Application rows now include link-resolution metadata so aggregator links can be resolved before future fill/submit workflows.
- Dashboard shows a link readiness chip and can call `POST /applications/{app_id}/resolve-link` to update a saved record with the resolved employer URL.
- The auto-apply path now requires a resolved supported ATS link; unresolved aggregator/company/unknown links are marked for review instead of browser automation.

## Milestone 5: Application Package UX

Status: Done

Goal:

Make generated materials easier to trust, scan, copy, and export.

Deliverables:

- Modal restyled with Influence Chart tokens.
- Tabs using compact segmented controls and lucide icons.
- Cover letter document panel.
- Tailored summary panel.
- Talking points as compact bullets.
- Q&A and interview prep as accordion rows.
- Company brief as structured detail blocks.
- Copy and PDF actions use shared buttons.

Acceptance criteria:

- The modal reads as a professional application workspace.
- Users can copy or export without hunting for actions.
- Long content scrolls inside the modal.
- Mobile layout remains usable.

Implementation notes:

- Preserve existing backend endpoint contracts while restyling.
- Add optimistic status update handling only after the shared status chip component exists.
- First modal restyle is implemented with tokenized header, status chips, action bar, tab icons, document panel, and structured content sections.

## Milestone 6: Auth, Account, and Subscription Readiness

Status: Done

Goal:

Move from prototype auth toward a model that can support paid plans and safe automation.

Deliverables:

- Replace `X-User-Email` prototype auth with real session or bearer token auth. Implemented with signed bearer tokens backed by server-side session records.
- User-scoped resumes and preferences. Implemented for upload, preferences save, user status, matching run, single-job analysis, application packages, and resume feedback.
- Subscription model with enforced quotas.
- Free/pro plan behavior:
  - Free: daily matching-run limit.
  - Pro: larger daily matching-run limit and browser fill-for-review access.
  - True auto-submit: keep gated server-side, blocked by default, and unavailable until an approved pilot.
- Account settings page. Implemented at `/settings` with billing, profile details, saved application answers, and submission guardrails.

Acceptance criteria:

- Users cannot access each other's resumes, preferences, applications, or profiles.
- Quotas are enforced server-side.
- UI displays remaining quota before starting a search.

Implementation notes:

- Stripe billing is implemented for Pro upgrades: Checkout creates the subscription, the Customer Portal handles billing management, and webhooks update `subscription_tier`.

## Milestone 7: Backend Data and API Hardening

Status: Done

Goal:

Make the backend maintainable, testable, and production safer.

Deliverables:

- Versioned migrations. Alembic scaffolding and a current-schema baseline exist now, with the lightweight startup runner still available as the local/dev fallback.
- Pydantic request/response schemas for public API contracts. Implemented for the main auth, profile, preferences, matching run, application history, single-job analysis, application package, status, resume feedback, and password reset flows.
- User ownership fields on resumes and preferences. Implemented with a versioned startup migration for existing local databases.
- Query parameters for applications sorting, filtering, and limiting. Implemented on `GET /applications`.
- Match buckets for the application pipeline. Implemented with `match_bucket=strong|below_threshold|all`; `all` excludes skipped/screened-out legacy rows.
- Account data export. Implemented with `GET /account/export` for resumes, preferences, generated package records, applications, matching runs, fill-review history, automation attempts, audits, and authenticated artifact URLs.
- Conservative pre-screen before LLM analysis. Implemented with pass/maybe/reject buckets; reject jobs are skipped without being saved.
- Server-side action guards for match quality. Implemented so package generation and fill-for-review are blocked for legacy screened-out jobs and jobs below the latest minimum match score.
- Matching run records and logs. Implemented with `AgentRun`; `/agent/run` now queues background work and the frontend polls run status.
- Safer auto-apply audit trail. Implemented with `AutoApplyAudit`; stronger confirmation rules remain.
- LLM provider setting per deployment. Implemented with `LLM_PROVIDER`, `LLM_MODEL`, and provider-specific model overrides flowing through the shared LLM factory.
- Structured error responses. Implemented at the FastAPI app boundary while preserving the existing `detail` field for current clients.

Acceptance criteria:

- Database can migrate from empty state.
- Tests cover auth boundaries, resume upload/preferences ownership, migration behavior, matching run persistence, quota enforcement, and application sorting/filtering.
- API contracts are explicit.
- Matching logs are persisted or retrievable after a run.

Implementation notes:

- User scoping should be addressed before broad UI work that depends on accurate per-user state.

## Milestone 8: Testing and QA

Status: Done

Goal:

Create a repeatable confidence loop.

Deliverables:

- Backend pytest suite. Implemented through the Dockerized preflight.
- Frontend typecheck and build checks. Implemented through `npm run build` in preflight.
- Frontend component smoke tests where practical. Current coverage is through the signed-in Playwright dashboard smoke until a dedicated component test runner is added.
- Playwright smoke test for the dashboard workflow. Implemented through `app.smoke.frontend_dashboard` in preflight, covering dashboard, Applications, and Account settings routes.
- Manual QA checklist. Implemented in `docs/MANUAL_QA_CHECKLIST.md`.
- Repeatable local/CI preflight command. Implemented through `./scripts/preflight.sh`.
- Answer-vault export/audit smoke test. Implemented through `scripts/preflight-answer-audit.mjs`.
- Answer-vault data-key re-encryption job. Implemented through `python -m app.jobs.reencrypt_application_answers --dry-run|--apply`.

Acceptance criteria:

- `npm run build` passes in `frontend`.
- Backend tests can run from one documented command.
- Local smoke coverage verifies auth bootstrap, resume upload, preferences save, answer-vault export/audit, dashboard rendering, application history rendering, and Account settings route rendering without live LLM or scraper calls.

Implementation notes:

- Mock JobSpy and LLM calls in tests.
- Keep live scraper and live LLM tests opt-in.
- `./scripts/preflight.sh` starts Docker Compose, verifies health endpoints, uses throwaway local users for answer-vault export/audit coverage, and runs a signed-in browser dashboard smoke without calling live LLMs.

## Milestone 9: Deployment Preparation

Status: Done

Goal:

Prepare the app for a hosted staging deployment.

Deliverables:

- Production Dockerfiles verified.
- Environment templates.
- CORS and frontend URL settings documented.
- Health and readiness endpoints. Implemented for API, DB, and worker.
- Logging strategy. Implemented with structured JSON operational events for matching runs, workers, browser fill-review, and submit confirmation.
- Background job or worker strategy for long matching runs. Implemented with worker mode and heartbeat checks.
- Deployment guide. Implemented through `docs/DEPLOYMENT_READINESS.md` and `docs/OPERATIONS_RUNBOOK.md`.
- CI preflight workflow. Implemented in `.github/workflows/preflight.yml`.

Acceptance criteria:

- App can run locally from a clean checkout.
- Hosted staging can be configured from docs.
- Long matching runs do not block the API request indefinitely.

## Deployment Gate

- No open implementation tasks remain for a guarded staging deployment.
- Keep `ENABLE_TRUE_AUTO_SUBMIT=false` until a controlled real-submit pilot has explicit approval, fixture coverage, and rollback procedures; keep pilot user/ATS allowlists empty outside that pilot.
- Before any hosted launch, run `./scripts/preflight.sh`, follow `docs/DEPLOYMENT_READINESS.md`, and complete `docs/MANUAL_QA_CHECKLIST.md`.
