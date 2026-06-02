# Job Finder Frontend

The frontend is a React 19 + TypeScript + Vite app that powers the Job Finder user workflow.

## Current Responsibilities

- Authentication modal and account state.
- Resume upload and extracted resume display.
- AI resume feedback.
- User profile form for application autofill and cover letters.
- Job preferences form.
- Agent run controls.
- Matched jobs and application history.
- Application package modal with generated materials.
- Admin scraper configuration.

## Key Files

- `src/App.tsx`: top-level app state, manual route handling, main workflow layout.
- `src/api/client.ts`: fetch helpers and API URL configuration.
- `src/components/Login.tsx`: login, register, forgot password.
- `src/components/OAuthCallback.tsx`: OAuth redirect handling.
- `src/components/ResetPassword.tsx`: reset-password view.
- `src/components/ResumeUpload.tsx`: upload, stored resume, extracted skills, summary.
- `src/components/ResumeFeedback.tsx`: AI resume analysis.
- `src/components/UserProfile.tsx`: profile details and completion state.
- `src/components/JobPreferences.tsx`: target role, experience, location, job type, companies, score, recency.
- `src/components/AgentControls.tsx`: agent launch and auto-submit toggle.
- `src/components/AgentDashboard.tsx`: matched jobs table and status.
- `src/components/ApplicationPackageModal.tsx`: cover letter, tailored summary, Q&A, interview prep, company brief, status updates.
- `src/components/AdminPanel.tsx`: scraper site configuration.
- `src/components/JobSearch.tsx` and `src/components/ProfileSettings.tsx`: older/standalone surfaces that are not currently central to `App.tsx`.

## Local Development

```bash
npm install
npm run dev
```

Default dev URL:

```text
http://localhost:5173
```

Build:

```bash
npm run build
```

Lint:

```bash
npm run lint
```

## Environment

The app reads:

```text
VITE_API_URL=http://localhost:8000
```

If `VITE_API_URL` is not set, `src/api/client.ts` falls back to `http://localhost:8000`.

## UI/UX Redesign Direction

The next frontend pass should use the Influence Chart design language:

- page background: `#f6f8fb`
- primary text: `#172033`
- muted text: `#657084`
- borders: `#dce2ea`
- soft panels: `#eef3f7`
- primary accent: `#176b63`
- accent soft: `#dff3ee`
- positive state: `#177245`

The product should read as a career operations dashboard:

- top app header
- compact workflow panels
- shared field, button, chip, table, and empty-state components
- application table as a first-class surface
- application package modal as a focused workspace

Avoid:

- decorative gradient blobs
- dark hero-first layout
- nested cards
- scattered indigo/violet gradients
- emoji-led controls
- inline SVGs where a standard icon exists

Full direction: `../docs/UI_UX_DIRECTION.md`.

## Implemented UI Foundation

The first Influence Chart-style UI pass is now in place:

- CSS variables live in `src/index.css`.
- Vite template styling has been removed from `src/App.css`.
- `lucide-react` is installed.
- Shared primitives live in `src/components/ui.tsx`.
- Main shell/header lives in `src/components/AppHeader.tsx`.
- Dashboard, setup workflow, run agent panel, application history table, application package modal, auth modal, and admin settings have been restyled.
- `/applications` now opens a full application history view.
- Application history rows show link readiness, can resolve supported aggregator links, and open the resolved employer URL when available.
- Resolved Greenhouse and Lever rows show `Fill review` and return a structured review summary without submitting.
- The fill-review modal shows recent saved review attempts for the selected application.
- Candidate Profile now includes `Application answers` for common application questions and optional self-identification fields.
- Application answers can be reset from the dashboard.

## Remaining Frontend Implementation Plan

1. Restyle `ResumeFeedback`, `ResetPassword`, `OAuthCallback`, `JobSearch`, and `ProfileSettings`.
2. Replace manual route branching with a small router as pages grow.
3. Tighten TypeScript types around API payloads.
4. Add component or Playwright smoke coverage for the main workflow.

## Known Frontend Issues

- `App.tsx` owns too much state and layout.
- Routing is manual and will become hard to maintain.
- Several components use `any`.
- Some older utility surfaces still use pre-redesign styling.
