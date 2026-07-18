# JobMatchKit Handoff

Keep this file current at the end of meaningful implementation sessions. It should describe the product as it exists now, not every retired experiment.

## Product Snapshot

- Product: JobMatchKit
- Core promise: let users maintain multiple resume-backed matching profiles, find strong-fit jobs for a selected profile, explain the match, track the pipeline, and generate downloadable application materials.
- Current submission model: users open employer links and submit manually. Browser form filling and final-submit automation are retired.
- Audience: job seekers who want a calmer, more systematic matching and application-material workflow.
- UI direction: calm, dense career-operations dashboard using the Influence Chart-inspired token system.
- Pricing: Free and Pro tiers are implemented; Stripe Checkout and Customer Portal support the `$10/month` Pro plan.

## Current Repository State

- Frontend: `frontend`, Vite React, Tailwind CSS 4, local shared UI primitives, `lucide-react` icons.
- Backend: `backend`, FastAPI, SQLModel, LangGraph worker workflow, provider-configurable LLM factory.
- Runtime: Docker Compose runs frontend, backend, worker, and Postgres.
- Brand/database defaults are standardized as JobMatchKit/`jobmatchkit`; some legacy local installs may still have older database names until migrated.
- Main workflow is implemented end to end:
  - account registration/login/logout and refresh sessions
  - resume upload and parsing
  - saved matching profiles that bind one resume to profile-specific roles, companies, locations, score thresholds, and recency
  - profile details and reusable application answers
  - matching preferences with multiple target roles and target companies
  - official employer source discovery, Fortune-style company fallback, and aggregator links only as hints
  - conservative pre-screen plus full fit scoring for likely matches
  - application persistence, status updates, and clear history
  - downloadable generated application packages
  - billing status, Pro upgrade, and customer portal
  - admin scraper configuration
- Matching runs can run in local background mode or worker mode, can be cancelled/stopped, and expose health/heartbeat signals.
- Product docs live in `README.md`, `backend/README.md`, `frontend/README.md`, `docs/IMPLEMENTATION_PLAN.md`, `docs/UI_UX_DIRECTION.md`, `docs/MANUAL_QA_CHECKLIST.md`, `docs/OPERATIONS_RUNBOOK.md`, and `docs/SECURITY_CHECKLIST.md`.

## Browser Automation Retirement

- Removed from UI: `Apply with assistant`, `Application Prep`, fill-review modals, screenshots/traces, submit-readiness controls, final-confirmation controls, and the submission guardrails panel.
- Removed from source: `browser-extension/`, the apply-assistant planner service, and frontend client helpers for retired application-prep routes.
- Backend legacy routes now return `410 Gone` with a retirement message:
  - `/agent/run?auto_apply=true`
  - `/applications/{app_id}/assistant-session`
  - `/assistant/session/{token}`
  - `/assistant/session/{token}/plan`
  - `/applications/{app_id}/fill-review`
  - `/applications/{app_id}/fill-reviews`
  - `/applications/{app_id}/automation-attempts`
  - `/applications/{app_id}/submit-readiness`
  - `/applications/{app_id}/submit-confirmation`
  - retired screenshot/trace artifact routes
- Historical database tables and serializers for fill-review/automation records remain for compatibility with older local data, account cleanup, and export safety. They are not product workflows.
- New generated packages label the combined prep document as `Application Notes`, not Application Prep.

## Active Technical Direction

- Keep the current Vite/FastAPI/Docker stack.
- Keep the app dashboard-first; no marketing landing page inside the signed-in workflow.
- Treat saved matching profiles as the unit of matching: each run should use an explicit profile/resume/preference bundle and should not silently switch to the latest resume.
- Prioritize official employer links and resolved ATS/company application URLs over job-board pages.
- Use job boards as discovery hints only when official sources are insufficient.
- Keep LLM usage focused on parsing, matching, explanation, and package generation.
- Keep browser automation out of the product unless a future plan is explicitly approved from scratch.

## UI/UX Target

Use the Influence Chart-inspired token system:

- Page: `#f6f8fb`
- Ink: `#172033`
- Muted: `#657084`
- Line: `#dce2ea`
- Soft: `#eef3f7`
- Accent: `#3658a8`
- Accent hover: `#2a4585`
- Accent soft: `#e8edfb`
- Positive: `#3f6fb5`

The app should feel like a calm career operations dashboard: compact workflow panels, clear readiness chips, scannable application tables, predictable controls, and no decorative clutter.

## Current Code Risks

- The repo may have unrelated local changes. Always inspect `git status --short` and touched files before editing.
- Keep `.env` private. Never commit provider keys or copied local secrets.
- Auth uses signed bearer tokens plus rotating refresh tokens in `localStorage`; server-side sessions, logout invalidation, refresh replay protection, and previous-secret rotation support are implemented.
- Application answer-vault string fields are encrypted at rest; answer-vault audits must never store answer values.
- Production-like startup rejects weak secrets, missing answer-vault encryption keys, wildcard CORS origins, and localhost CORS origins.
- Daily free/pro matching-run quotas are enforced server-side and shown in the UI.
- Historical fill-review/automation tables still exist. Do not rewire them into UI without a new approved plan.
- Matching-profile migration must preserve existing local data by creating a default profile from each user's latest resume and latest preferences.

## Session Start Checklist

- Read this file.
- Read `docs/IMPLEMENTATION_PLAN.md` and `docs/UI_UX_DIRECTION.md` when changing product behavior or UI.
- Check `git status --short`.
- Inspect changed files before editing.
- Avoid reverting user changes.

## Session End Checklist

- Summarize completed work.
- Record important files changed.
- Note tests/checks run.
- Note blockers or residual risks.
- Update this handoff if product behavior changed.

## Latest Session Notes

- Planned saved matching profile feature: users can maintain multiple named profile tracks, each linked to one resume and its own matching preferences. Matching runs and applications should record the selected profile to keep results auditable and filterable.

- Removed Apply with assistant and Application Prep from the dashboard and pipeline UI.
- Removed the retired submission guardrails panel from dashboard setup and account settings.
- Reworded Application Answers as reusable answers for generated materials, not form filling.
- Retired automation/prep API paths with `410 Gone` responses and updated backend contract tests.
- Deleted the browser extension source and frontend unsupported-ATS helper.
- Verified `frontend npm run build` and full Dockerized backend API contracts: `87 passed, 4 warnings`.
