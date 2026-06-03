# Auto-Apply Reliability Plan

Last updated: 2026-06-01

This plan describes how to make auto-apply reliable enough for real users. The core principle is that auto-apply should be a controlled submission system, not an unrestricted browser bot.

## Product Stance

The application should support three increasingly automated modes:

1. `Prepare only`: find best-fit jobs and generate application materials.
2. `Fill for review`: fill supported application forms, save evidence, and stop before final submission.
3. `Auto-submit`: submit only when the job, applicant data, form, and supported ATS adapter all pass confidence and safety checks.

`Fill for review` should ship before broad auto-submit. It gives users useful time savings while creating the screenshots, logs, and field-mapping data needed to make submission safer.

## Reliability Principles

- Submit only on supported ATS platforms.
- Prefer deterministic adapters over LLM selector guessing.
- Use LLMs only for bounded tasks, such as drafting short answers to application questions from known resume/profile data.
- Never invent sensitive or legally significant answers.
- Stop for human review when confidence is low.
- Store every attempt as an auditable state transition.
- Keep matching/scoring completely separate from demographic and voluntary self-identification data.

## Phased Implementation

### Phase 1: Fill For Review

Goal:

Make browser automation useful without final submission risk.

Deliverables:

- Open application pages with Playwright.
- Detect supported ATS type.
- Fill standard profile fields.
- Upload resume.
- Fill generated cover letter or application Q&A where supported.
- Stop before final submit.
- Save filled-field summary, missing-field summary, and blocker reason.
- Return an ephemeral screenshot preview for the current review session.
- Persist authenticated screenshots and traces before production auto-submit.
- Mark the application as `Needs Review`.

Acceptance criteria:

- A user can open a matched job, choose fill-for-review, and see exactly what was filled.
- Unsupported forms never submit.
- Missing or ambiguous required fields produce a review state, not a failed silent action.

Current implementation:

- `POST /applications/{app_id}/fill-review` runs a safe review session for a signed-in user's saved application.
- Each fill-review attempt is saved as an `ApplicationFillReview` record with filled fields, missing fields, blockers, status, and timestamp.
- `GET /applications/{app_id}/fill-reviews` returns the signed-in user's saved review attempts for that application.
- `DELETE /applications/{app_id}/fill-reviews` clears the signed-in user's saved review attempts for that application.
- The first deterministic ATS adapters are Greenhouse, Lever, Ashby, SmartRecruiters, Workday, BambooHR, iCIMS, Recruitee, and Taleo.
- The supported ATS adapters fill standard contact fields, upload the saved resume, use consented application-answer fields where possible, and never click submit.
- The application is marked `Needs Review` after the fill-review attempt.
- The dashboard shows `Fill review` for resolved supported ATS applications and returns filled fields, missing fields, blockers, an ephemeral screenshot preview, and the application URL.
- Fill-review screenshots and Playwright traces are saved as local authenticated artifacts; saved review history can preview screenshots and download traces.
- User-scoped submission guardrails and `POST /applications/{app_id}/submit-readiness` evaluate whether a prepared application could move to a future final-confirm step without clicking submit.
- `POST /applications/{app_id}/submit-confirmation` runs the readiness gate, detects the final submit control with deterministic heuristics, records an audit event, and still does not click submit.
- `AutoApplyAttempt` records now persist fill-review and final-confirmation status, field summaries, blockers, artifacts, readiness snapshots, submit-control evidence, and attempt-linked audit events. `GET /applications/{app_id}/automation-attempts` exposes the signed-in user's attempt history.

### Phase 2: Application Link Resolution

Goal:

Resolve aggregator links to the real employer or ATS application page before any filling logic runs.

Why:

Many discovery URLs point to places like LinkedIn Jobs, Indeed, Google Jobs, Glassdoor, or ZipRecruiter. These links are not always the final application form. The assistant should classify the original link, attempt safe resolution where possible, and store both the original and resolved destinations.

Deliverables:

- Add `ApplicationLinkResolver`.
- Store `source_url`, `resolved_url`, `source_type`, `ats_type`, `resolution_status`, and `resolution_notes` on applications.
- Classify direct ATS links without opening a browser.
- Classify aggregator links as `needs_resolution`.
- Classify direct company/careers links as `resolved` but still requiring ATS/form support checks before auto-submit.
- Add a conservative Playwright resolver for aggregator pages.
- Expose a user-triggered resolve action in the application dashboard.

Source types:

- `linkedin`
- `indeed`
- `google_jobs`
- `ziprecruiter`
- `glassdoor`
- `company_site`
- `ats`
- `unknown`

Resolution statuses:

- `resolved`
- `needs_resolution`
- `login_required`
- `captcha`
- `manual_review`
- `unsupported`

Resolution object:

```json
{
  "original_url": "https://www.linkedin.com/jobs/view/123",
  "resolved_url": null,
  "source_type": "linkedin",
  "ats_type": null,
  "resolution_status": "needs_resolution",
  "notes": "Aggregator job link must be opened and resolved to the employer application URL before form filling."
}
```

LinkedIn-specific stance:

- External links such as `Apply on company website` can be resolved when no login wall or captcha blocks access.
- LinkedIn Easy Apply should not be auto-submitted in the first implementation.
- Logged-in LinkedIn automation should be treated as a separate product/legal/compliance decision.

Acceptance criteria:

- Application records preserve the original discovery URL.
- Direct ATS links are marked `resolved` with an `ats_type`.
- Aggregator links are marked `needs_resolution` and never sent directly to form filling.
- Unknown links go to review instead of auto-submit.
- The dashboard can resolve a saved aggregator link and open the resolved employer URL when one is found.

Current implementation:

- `ApplicationLinkResolver.classify_url` handles direct ATS links, aggregator links, company/careers links, and unknown URLs.
- `ApplicationLinkResolver.resolve_url` opens aggregator links with Playwright only when the link requires resolution.
- The resolver searches for clear external employer/application links and detects common login/captcha blockers.
- `POST /applications/{app_id}/resolve-link` updates the saved application record for the signed-in user.
- The dashboard shows link readiness and offers `Resolve link` when the record is not already resolved.
- The current auto-apply path now holds unresolved aggregator, company-site, unknown, or unsupported links for review instead of sending them into browser automation.
- Logged-in aggregator flows and LinkedIn Easy Apply remain out of scope for this first implementation.

### Phase 3: ATS Adapters

Goal:

Replace generic form guessing with board-specific adapters.

Initial adapters:

- Greenhouse. Initial fill-for-review adapter implemented.
- Lever. Initial fill-for-review adapter implemented.
- Ashby. Initial fill-for-review adapter implemented.
- SmartRecruiters. Initial fill-for-review adapter implemented.
- Workday. Initial fill-for-review adapter and account-gate detection implemented.
- BambooHR. Initial fill-for-review adapter implemented.
- iCIMS. Initial fill-for-review adapter implemented.
- Recruitee. Initial fill-for-review adapter implemented.
- Taleo. Initial fill-for-review adapter implemented.

Later adapters:

- Add more vendor-specific adapters as new job sources are observed.

Each adapter should own:

- URL/domain detection.
- Page readiness checks.
- Required field discovery.
- Field selector map.
- Resume upload verification.
- Standard answer filling.
- Custom question handling.
- Final submit detection.
- Success page / confirmation detection.

The current `BrowserApplyService` can remain as a fallback only for `Fill for review` unless a tightly scoped real-submit pilot is explicitly approved.

### Phase 4: Submission State Machine

Goal:

Make each attempt inspectable, resumable, and debuggable.

Recommended states:

- `queued`
- `opened`
- `detected_ats`
- `profile_validated`
- `resume_uploaded`
- `fields_filled`
- `blocked_needs_review`
- `ready_to_submit`
- `submitted`
- `failed`

Recommended model:

`AutoApplyAttempt`

- `id`
- `user_id`
- `application_id`
- `agent_run_id`
- `job_url`
- `job_title`
- `company`
- `ats_type`
- `mode`: `prepare_only`, `fill_for_review`, `auto_submit`
- `status`
- `confidence_score`
- `blocked_reason`
- `steps` JSON
- `filled_fields` JSON
- `missing_fields` JSON
- `custom_questions` JSON
- `screenshot_path`
- `trace_path`
- `submitted_at`
- `created_at`
- `updated_at`

The existing `AutoApplyAudit` can either be expanded or kept as the append-only event log under this attempt record.

Current implementation:

- `AutoApplyAttempt` exists as the workflow record for fill-review and final-confirmation checks.
- Fill-review creates an attempt and links the saved `ApplicationFillReview` plus screenshot/trace artifact paths.
- Final confirmation updates the latest attempt with readiness and submit-control snapshots and links the audit event back to the attempt.
- Each attempt now stores compact step transitions such as `attempt_created`, `inputs_validated`, `browser_fill_started`, `fill_review_completed`, `readiness_checked`, `submit_control_detection`, and `final_confirmation_prepared`.
- The dashboard shows an automation timeline in the fill-review modal, including the latest step transitions for each attempt.

## Pre-Screen Cost Gate

Before full AI fit analysis, the matching workflow should run a cheap, high-recall screen so obvious non-fits do not spend LLM budget.

Implemented behavior:

- Jobs are classified as `pass`, `maybe`, or `reject` before the full LLM fit analysis.
- `pass` and `maybe` jobs continue to AI analysis.
- `reject` jobs are persisted as `Screened Out` with `pre_screen_reasons`, but they do not enter the AI analysis batch.
- The screen rejects only clear preference conflicts, such as senior role preference vs. junior/internship title, full-time preference vs. contract/part-time title, or remote preference vs. clearly on-site posting.
- Weak role-keyword overlap is never a hard reject; it becomes `maybe` so the full AI analysis can still catch good but unusually written postings.
- The application API exposes `match_bucket=strong|below_threshold|screened_out|all`.
- The dashboard defaults to `Strong matches`, with separate lanes for below-threshold and screened-out jobs.
- Package generation and fill-for-review are blocked server-side for screened-out jobs and jobs below the latest minimum match score.

This keeps the pre-screen conservative enough to avoid eliminating good matches while still reducing avoidable LLM and package-generation cost.

### Phase 5: Hard Stop Rules

Auto-submit must stop for review when any of these happen:

- Unsupported ATS or unknown form pattern.
- Aggregator link still has `needs_resolution`.
- Link resolution ended in `login_required`, `captcha`, `manual_review`, or `unsupported`.
- Login wall.
- Captcha or bot challenge.
- Resume upload cannot be verified.
- Submit button cannot be confidently identified.
- Required field is missing a trusted answer.
- Required custom question cannot be answered from resume/profile/package data.
- Work authorization answer is missing.
- Sponsorship answer is missing.
- EEO/self-identification field lacks a clear user-selected answer or a clear `Decline to self-identify` option.
- Disability, veteran, race, gender, or other sensitive answers would need to be inferred.
- Salary, relocation, background-check consent, or legal attestation requires new user confirmation.
- The form asks for SSN, government ID, date of birth, financial data, or document numbers.
- The page redirects to an unexpected domain.
- The company or domain is on the user's denylist.

### Phase 6: User Controls

Add an `Automation settings` surface.

Recommended controls:

- Default mode: `Prepare only`, `Fill for review`, or `Auto-submit supported matches`.
- Minimum match score for auto-submit.
- Max auto-submits per day.
- Supported ATS only toggle.
- Company allowlist.
- Company denylist.
- Target job title allowlist.
- Require review for custom questions.
- Require review for salary questions.
- Require review for work authorization or sponsorship questions.
- Save screenshots/traces toggle.
- Auto-submit consent timestamp.

The default should be conservative: `Prepare only`.

## Application Response Profile

Reliable auto-apply needs more than a resume and basic profile. Add a separate `ApplicationResponseProfile` or `ApplicationAnswerVault` instead of overloading `Profile`.

### Standard Application Answers

These are useful for reliable filling and should be included before auto-submit:

- Legal first name.
- Legal last name.
- Preferred name.
- Email.
- Phone.
- Address/city/state/country.
- LinkedIn URL.
- Portfolio URL.
- GitHub URL.
- Work authorization country.
- Authorized to work in the target country.
- Requires sponsorship now.
- Requires sponsorship in the future.
- Current visa or work status, optional and user-entered only.
- Willing to relocate.
- Willing to commute.
- Preferred work arrangement.
- Desired salary range.
- Earliest start date.
- Years of experience.
- Education summary.
- Work history summary.
- Over 18 confirmation, where needed.

Do not store I-9 documents, SSN, passport numbers, driver's license numbers, or other government ID numbers for this product stage.

Current implementation:

- `ApplicationAnswerProfile` stores common application answers separately from the main candidate profile.
- `GET /application-profile` returns the signed-in user's saved answers.
- `GET /application-profile/export` returns a user-owned export payload for download.
- `GET /application-profile/audit` returns recent answer-vault access events.
- `POST /application-profile` upserts the signed-in user's saved answers.
- `DELETE /application-profile` resets the signed-in user's saved answers.
- `/user/status` includes `application_profile` so the dashboard can preload saved answers.
- The dashboard includes an `Application answers` section under Candidate Profile.
- The `Application answers` section includes export and reset actions for saved answers and optional self-identification values.
- `consent_to_use_answers` must be enabled before future fill-for-review logic can use the stored common answers.
- Sensitive self-identification answers are reset to `prefer_not_to_answer` unless `consent_to_use_demographics` is explicitly enabled.
- `ApplicationAnswerAudit` records view, export, reset, dashboard preload, fill-for-review, and submit-readiness access without storing answer values.
- `APP_DATA_PREVIOUS_ENCRYPTION_KEYS` can keep older encrypted answer rows readable during a planned data-key rotation.
- Government ID numbers and I-9 documents remain out of scope.

### Work Authorization

Yes, the app should collect work authorization answers if auto-submit is planned. Many applications ask whether the applicant is authorized to work in a country and whether sponsorship is needed now or in the future.

Keep this lightweight:

- Ask only the application-level questions needed for forms.
- Do not ask for I-9 documents.
- Do not ask the user to upload identity or work-authorization documents.
- Treat unknown answers as blockers.

For U.S. jobs, Form I-9 is an employer post-hire verification process. USCIS says employers use Form I-9 to verify identity and employment authorization for individuals hired for employment, and employees present acceptable documents to the employer. That is different from pre-application work authorization questions.

Reference:

- USCIS Form I-9 overview: https://www.uscis.gov/i-9
- USCIS employee rights: https://www.uscis.gov/i-9-central/employee-rights-and-resources/employee-rights

### Voluntary Self-Identification

Race, ethnicity, gender, veteran status, and disability questions should be treated as sensitive voluntary self-identification data.

Recommendation:

- Do not require these fields for MVP auto-apply.
- Add them only as optional user-controlled answers.
- Default each field to `Prefer not to answer`.
- Never infer or generate these answers.
- Never send these answers to matching/scoring prompts.
- Never use these answers for ranking, filtering, or deciding which applications to submit.
- Store separately from profile and preferences.
- Encrypt at rest before production.
- Record explicit consent before using them to fill applications.
- Let users delete or reset them independently.

If an application form offers `Decline to self-identify`, `I do not wish to answer`, or similar options, the assistant can use that option when the user has not provided an explicit answer. If the form makes a sensitive field required without a decline option, stop for review.

References:

- EEOC pre-employment race guidance: https://www.eeoc.gov/pre-employment-inquiries-and-race
- EEOC pre-employment gender guidance: https://www.eeoc.gov/pre-employment-inquiries-and-gender
- EEOC pre-employment disability guidance: https://www.eeoc.gov/pre-employment-inquiries-and-disability
- OFCCP Voluntary Self-Identification of Disability form: https://www.dol.gov/sites/dolgov/files/ofccp/regs/compliance/sec503/Self_ID_Forms/VoluntarySelf-ID_CC-305_ENG_JRF_QA_508c.pdf

## Security And Privacy

Before enabling real auto-submit:

- Keep sensitive application response data encrypted at rest.
- Separate normal profile data from sensitive self-ID data.
- Add an audit trail for reads and writes to sensitive data.
- Add user-facing export/delete controls.
- Keep screenshots and traces behind authenticated access.
- Keep retention windows enforced for traces and screenshots.
- Avoid logging sensitive answers in plaintext.
- Avoid sending sensitive self-ID answers to LLM providers.

## Current Submit Boundary

The current implementation is intentionally a fill-for-review system, not a true auto-submit system.

Implemented boundary:

- The deterministic ATS services fill supported forms and stop before final submit.
- `POST /applications/{app_id}/submit-readiness` evaluates policy and readiness but returns `can_submit=false`.
- `POST /applications/{app_id}/submit-confirmation` detects the final submit control without clicking it and returns `can_submit=false`.
- The legacy `BrowserApplyService` blocks `submit=True` unless `ENABLE_TRUE_AUTO_SUBMIT=true`.
- `.env.example` and Docker Compose default `ENABLE_TRUE_AUTO_SUBMIT=false`.
- Application answer-vault string fields are encrypted before persistence.
- Fill-review screenshots and traces are authenticated and pruned by retention policy.

Do not enable `ENABLE_TRUE_AUTO_SUBMIT=true` for normal development, demos, or staging smoke tests.

## True Auto-Submit Pilot Gates

A real-submit pilot should be treated as a controlled release, not a normal feature toggle.

Required before enabling the flag:

- Written user approval for the pilot scope and supported ATS list.
- A small allowlist of test users and companies/domains.
- `APP_ENV=production` or a named staging environment with production-like secrets and logging.
- Alembic enabled and validated against a copy of existing data.
- Verified encryption-at-rest behavior for sensitive application answers and artifact metadata.
- Verified retention windows for screenshots, traces, and fill-review artifacts.
- Fixture coverage for every supported ATS final-submit path, including ready, blocked, ambiguous, login-gated, captcha-gated, and multi-step cases.
- A dry-run record for each attempted application showing filled fields, missing fields, blockers, submit-control selector, confidence, and final URL.
- A per-job confirmation screen that shows the exact final action and requires explicit user confirmation.
- A rollback plan that can disable true submit immediately by setting `ENABLE_TRUE_AUTO_SUBMIT=false`.
- Monitoring for submit attempts, blocked attempts, external navigation failures, captchas, account/login gates, and unexpected redirects.

First pilot constraints:

- Keep final submit pro/admin-only.
- Keep human confirmation required per job.
- Only allow direct supported ATS URLs, not unresolved aggregators.
- Only allow high-confidence submit-control detection.
- Stop on any sensitive self-ID question without a decline option.
- Stop on missing required work authorization, sponsorship, or profile answers.
- Stop on captcha, login, payment, assessment, or external account creation gates.
- Keep the daily submit cap low.

## Worker Architecture

Browser automation should move out of the API process before production.

Recommended architecture:

- API queues persisted agent runs and future `AutoApplyAttempt` jobs.
- Worker process runs queued agent work and future Playwright submission attempts.
- Worker writes attempt state transitions.
- Frontend polls attempt/run status.
- Browser traces and screenshots are stored as artifacts.
- Queue supports retries, timeouts, concurrency limits, and dead-letter handling.

Candidate tools:

- Celery + Redis
- RQ + Redis
- Dramatiq + Redis
- Arq for asyncio-native jobs

## Testing Strategy

### Unit Tests

- ATS detection.
- Field schema normalization.
- Work authorization answer validation.
- Sensitive field handling.
- Hard stop rule evaluation.

### Playwright Fixture Tests

Create local fixture pages for:

- Greenhouse simple form.
- Lever simple form.
- Ashby simple form.
- Form with resume upload failure.
- Form with required custom questions.
- Form with voluntary self-ID questions.
- Form with captcha placeholder.
- Form with final submit confirmation.

Current fixture coverage:

- Static HTML fixtures cover a clean Greenhouse-style final submit control, ambiguous submit controls, and captcha-blocked pages for the deterministic submit-control detector.

### Integration Tests

- Queue an auto-apply attempt.
- Worker fills fixture form.
- Attempt reaches `blocked_needs_review` or `submitted` as expected.
- Screenshot/trace paths are recorded.
- Audit events are written.

## MVP Recommendation

First reliable version:

- `Prepare only` remains default.
- Add `Fill for review`.
- Support Greenhouse, Lever, Ashby, SmartRecruiters, Workday, BambooHR, iCIMS, Recruitee, and Taleo first.
- Add `ApplicationAnswerVault` for work authorization and common application answers.
- Add optional sensitive self-ID fields with `Prefer not to answer` defaults.
- Keep true auto-submit pro/admin-only.
- True auto-submit only for supported ATS, high-confidence forms, complete work authorization answers, and no sensitive/question blockers.

This gives the user practical automation while preserving trust, auditability, and control.
