# Manual QA Checklist

Use this checklist after `./scripts/preflight.sh` passes and before sharing a hosted staging build or testing with real user data.

## Docker Baseline

- Run `./scripts/preflight.sh` from the repository root.
- Confirm the frontend is available at `http://localhost:5173`.
- Confirm `GET /health`, `GET /health/db`, and `GET /health/worker` are healthy.
- Keep `.env` private and confirm provider keys are not copied into docs, screenshots, or tickets.

## Auth And Account

- Register a new user.
- Sign out and sign back in with the same user.
- Open `Account` from the header.
- Save profile details.
- Save application answers with demographic consent off and confirm optional self-ID answers remain `prefer_not_to_answer`.
- Export application answers and confirm the audit entry appears.
- Export account data from the header and confirm the JSON is scoped to the signed-in user.
- Reset application answers only after confirming the destructive prompt appears.

## Dashboard Workflow

- Upload a resume.
- Save job preferences with a minimum match score.
- Confirm the dashboard overview strip marks Resume, Profile, Preferences, and Daily runs clearly.
- Start matching from the dashboard.
- Confirm the run status changes without blocking the page.
- Confirm the recent jobs panel stays aligned and does not overflow after data loads.

## Application Pipeline

- Open `Applications`.
- Confirm strong matches, below-threshold jobs, screened-out jobs, and all tracked jobs are separated by the lane controls.
- Confirm below-threshold and screened-out jobs are review-only and cannot generate packages or fill-review actions.
- Resolve an aggregator link only when a safe resolved employer URL is found.
- Confirm unsupported, login-gated, captcha-gated, or unresolved links stay in review states.

## Generated Package

- Open a qualifying matched job.
- Generate the application package.
- Confirm cover letter, tailored summary, talking points, Q&A, interview prep, and company brief are readable.
- Download the generated package.
- Download the cover-letter PDF.
- Update application status and confirm the pipeline reflects the change.

## Fill-For-Review Safety

- Use a pro/admin account before testing browser fill-for-review.
- Confirm `Fill review` appears only for resolved supported ATS links.
- Run fill-for-review on a test or fixture-safe application URL.
- Confirm the app fills available fields, lists missing fields and blockers, saves a review record, and never clicks final submit.
- Preview the saved screenshot and download the trace only while signed in.
- Clear saved fill-review attempts and confirm artifact links disappear.

## True-Submit Gate

- Confirm `ENABLE_TRUE_AUTO_SUBMIT=false` for normal local, staging, and demo use.
- Confirm submission guardrails show the pilot as locked unless the global flag and pilot allowlist explicitly approve the user.
- Confirm `Inspect final step` can detect submit controls without clicking them.
- Confirm submit confirmation still reports `can_submit=false` outside an approved pilot.

## Admin And Operations

- With an admin account, open `/admin`.
- Save scraper settings and confirm non-admin users cannot access the admin API.
- Review structured logs for agent run, worker, fill-review, submit-readiness, and submit-confirmation events.
- Run the answer-vault re-encryption job in dry-run mode before any data-key rotation.
