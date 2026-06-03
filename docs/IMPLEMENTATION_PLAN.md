# Job Finder Implementation Plan

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

Issues to address:

- The UI is currently a mix of dark hero, indigo/violet gradients, emoji controls, inline SVGs, and plain gray fields.
- `src/App.css` previously contained Vite template styles; those have been replaced with a minimal note.
- There is no shared app shell or component system.
- Manual routing in `App.tsx` will get brittle as pages grow.
- The "View all applications" behavior is inline instead of a true route.
- Auth uses signed bearer tokens and rotating refresh tokens stored in `localStorage`; server-side invalidation, refresh replay protection, and previous-secret verification for key rotation are implemented.
- Frontend state uses `any` in several places, which hides API contract drift.

### Backend

The backend is a FastAPI app in `backend/`.

Key files:

- `main.py`: FastAPI app, CORS, DB table creation, router mount.
- `app/api/endpoints.py`: auth, OAuth callbacks, resume upload, preferences, profile, agent run, applications, admin config, password reset, application package, status update, resume feedback.
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

- The agent workflow is cleanly separated into LangGraph nodes.
- LLM provider selection is centralized.
- Application persistence includes useful URL and title/company dedupe.
- The application package endpoint already produces high-value artifacts.
- Admin scraper configuration exists.

Issues to address:

- Resume and preferences are now user-scoped in the core backend flows.
- Auth now uses signed bearer tokens with server-side session records, logout invalidation, rotating refresh tokens, replay protection, and previous-secret verification for key rotation.
- Startup can run an Alembic baseline when `USE_ALEMBIC_MIGRATIONS=true`; local/dev still defaults to `create_all` plus the lightweight `schema_migrations` table.
- Core public API request and response schemas are explicit for the main app flows.
- Daily free/pro run quotas are enforced server-side.
- Agent runs are persisted as queued records, can run in local background mode, and can be processed by the Docker worker service in worker mode.
- Browser fill-for-review is gated to pro/admin users; true final submit is hard-blocked by default with `ENABLE_TRUE_AUTO_SUBMIT=false`.
- Auto-apply reliability, ATS adapters, hard stop rules, work authorization, and voluntary self-ID handling are documented in `docs/AUTO_APPLY_RELIABILITY_PLAN.md`.
- The application answer vault foundation is implemented with `ApplicationAnswerProfile`, `GET/POST /application-profile`, and a dashboard `Application answers` section.
- Fill-for-review adapters are implemented for resolved Greenhouse, Lever, Ashby, SmartRecruiters, Workday, BambooHR, iCIMS, Recruitee, and Taleo links via `POST /applications/{app_id}/fill-review`.
- Fill-review attempts are now saved as application-scoped history through `ApplicationFillReview` and `GET /applications/{app_id}/fill-reviews`.
- Fill-review screenshots and Playwright traces are persisted as authenticated local artifacts and surfaced from saved review history.
- Final-submit guardrails are implemented with user-scoped submission settings, per-application readiness checks, a no-click final confirmation endpoint with fixture-backed submit-control detection, and persisted `AutoApplyAttempt` records tying fill-review and confirmation into one auditable workflow. Attempts now include compact step-level telemetry for fill-review and final-confirmation transitions. Actual final submission remains disabled.
- A focused backend API contract suite now covers auth, ownership, migrations, application queries, quotas, and agent run persistence.

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

- A future session can understand the app, current risks, UI direction, and next tasks from docs alone.
- Generated files such as `__pycache__`, `.env`, `node_modules`, and build output are ignored.

Implementation notes:

- Added root `.gitignore` and `.env.example`.
- Added `docs/AUTO_APPLY_RELIABILITY_PLAN.md` for the reliability path before production auto-submit.
- Decide later whether to keep the displayed brand as "Job Hunter" or rename all UI copy to "Job Finder". The current shell uses "Job Finder".

## Milestone 1: Design System Foundation

Status: In progress

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
- Remaining old-style surfaces include `ResumeFeedback`, `ResetPassword`, `OAuthCallback`, `JobSearch`, and `ProfileSettings`.

## Milestone 2: App Shell and Navigation

Status: In progress

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

Status: In progress

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

Implementation notes:

- Keep the current refs-based save/upload flow for the first restyle if needed.
- After visual parity is reached, replace refs with a clearer parent state machine.

## Milestone 4: Application Pipeline and History

Status: In progress

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

Status: In progress

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

Status: In progress

Goal:

Move from prototype auth toward a model that can support paid plans and safe automation.

Deliverables:

- Replace `X-User-Email` prototype auth with real session or bearer token auth. Implemented with signed bearer tokens backed by server-side session records.
- User-scoped resumes and preferences. Implemented for upload, preferences save, user status, agent run, single-job analysis, application packages, and resume feedback.
- Subscription model with enforced quotas.
- Free/pro plan behavior:
  - Free: daily agent-run limit.
  - Pro: larger daily agent-run limit and browser fill-for-review access.
  - True auto-submit: keep gated server-side, blocked by default, and unavailable until an approved pilot.
- Account settings page.

Acceptance criteria:

- Users cannot access each other's resumes, preferences, applications, or profiles.
- Quotas are enforced server-side.
- UI displays remaining quota before starting a search.

Implementation notes:

- This should happen before production deployment.
- It can be implemented without external billing first, then wired to Stripe later.

## Milestone 7: Backend Data and API Hardening

Status: In progress

Goal:

Make the backend maintainable, testable, and production safer.

Deliverables:

- Versioned migrations. Alembic scaffolding and a current-schema baseline exist now, with the lightweight startup runner still available as the local/dev fallback.
- Pydantic request/response schemas for public API contracts. Implemented for the main auth, profile, preferences, agent run, application history, single-job analysis, application package, status, resume feedback, and password reset flows.
- User ownership fields on resumes and preferences. Implemented with a versioned startup migration for existing local databases.
- Query parameters for applications sorting, filtering, and limiting. Implemented on `GET /applications`.
- Match buckets for the application pipeline. Implemented with `match_bucket=strong|below_threshold|screened_out|all`.
- Conservative pre-screen before LLM analysis. Implemented with pass/maybe/reject buckets, persisted screened-out reasons, and dashboard review lanes.
- Server-side action guards for match quality. Implemented so package generation and fill-for-review are blocked for screened-out jobs and jobs below the latest minimum match score.
- Agent run records and logs. Implemented with `AgentRun`; `/agent/run` now queues background work and the frontend polls run status.
- Safer auto-apply audit trail. Implemented with `AutoApplyAudit`; stronger confirmation rules remain.
- LLM provider setting per run or per deployment.
- Structured error responses.

Acceptance criteria:

- Database can migrate from empty state.
- Tests cover auth boundaries, resume upload/preferences ownership, migration behavior, agent run persistence, quota enforcement, and application sorting/filtering.
- API contracts are explicit.
- Agent logs are persisted or retrievable after a run.

Implementation notes:

- User scoping should be addressed before broad UI work that depends on accurate per-user state.

## Milestone 8: Testing and QA

Status: Not started

Goal:

Create a repeatable confidence loop.

Deliverables:

- Backend pytest suite.
- Frontend typecheck and build checks.
- Frontend component smoke tests where practical.
- Playwright smoke test for the main workflow.
- Manual QA checklist.

Acceptance criteria:

- `npm run build` passes in `frontend`.
- Backend tests can run from one documented command.
- A local smoke test verifies login/register, profile save, resume upload, preferences save, agent run with mocked external dependencies, and application history rendering.

Implementation notes:

- Mock JobSpy and LLM calls in tests.
- Keep live scraper and live LLM tests opt-in.

## Milestone 9: Deployment Preparation

Status: Not started

Goal:

Prepare the app for a hosted staging deployment.

Deliverables:

- Production Dockerfiles verified.
- Environment templates.
- CORS and frontend URL settings documented.
- Health and readiness endpoints.
- Logging strategy.
- Background job or worker strategy for long agent runs.
- Deployment guide.

Acceptance criteria:

- App can run locally from a clean checkout.
- Hosted staging can be configured from docs.
- Long agent runs do not block the API request indefinitely.

## Immediate Next Implementation Order

1. Add export/delete controls and deeper audit events for sensitive answer-vault reads.
2. Rehearse staging with `USE_ALEMBIC_MIGRATIONS=true` against a database copy and verify `/health`, `/health/db`, and `/health/worker`.
3. Keep `ENABLE_TRUE_AUTO_SUBMIT=false` until a controlled real-submit pilot has explicit approval, fixture coverage, and rollback procedures.
4. Use `docs/DEPLOYMENT_READINESS.md` as the staging checklist for CORS, worker, backup/restore, and provider-key rotation checks.
