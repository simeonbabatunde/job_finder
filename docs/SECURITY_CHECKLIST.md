# Security Checklist

Use this checklist before sharing the project, deploying staging, or enabling any browser automation beyond fill-for-review.

## Local Secrets

- Keep `.env` private. It is intentionally ignored by git.
- Use `.env.example` for placeholders only; never add real provider keys there.
- Rotate any OpenAI, OpenRouter, Google, SMTP, or OAuth secret that was pasted into chat, docs, screenshots, or committed history.
- Run `git grep -n -E '(sk-[A-Za-z0-9]|OPENAI_API_KEY=.+|OPENROUTER_API_KEY=.+|GOOGLE_API_KEY=.+)'` before commits that touch config or docs. Expected matches should be variable names or blank placeholders only.

## Required Production Settings

- Set `APP_ENV=production`.
- Set a strong `AUTH_SECRET_KEY` with at least 32 random characters.
- Use `AUTH_PREVIOUS_SECRET_KEYS` only during planned key rotation.
- Keep `ENABLE_TRUE_AUTO_SUBMIT=false` until a real-submit pilot has explicit approval and fixture coverage.
- Set `USE_ALEMBIC_MIGRATIONS=true` in staging after validating the baseline against a copy of existing data.
- Use provider API keys with least-privilege scopes where the provider supports scoping.

## User Data

- Treat resumes, profile data, application answers, screenshots, traces, and generated packages as private user data.
- Store voluntary self-ID answers separately from matching preferences.
- Default voluntary self-ID answers to `prefer_not_to_answer`.
- Do not send voluntary self-ID answers to LLM prompts for matching, scoring, or ranking.
- Add encryption at rest before production storage of sensitive application answers.
- Provide export/delete/reset controls for saved application answers and automation artifacts.

## Browser Automation

- Fill-for-review may prepare supported ATS forms, but it must stop before final submit.
- Final-submit readiness and confirmation endpoints must keep `can_submit=false` until an approved pilot changes that behavior.
- Screenshots and Playwright traces must remain behind authenticated endpoints.
- Set a retention window for screenshots and traces before production.
- Avoid logging filled field values, answers, resume text, tokens, and provider keys.

## Deployment

- Run backend tests, frontend lint/build, `docker compose config`, and an E2E Docker smoke test before staging.
- Confirm CORS only allows the deployed frontend origin.
- Confirm Postgres credentials are not the default local values.
- Confirm the worker process is running when `AGENT_RUNNER_MODE=worker`.
- Confirm backups and restore testing for the production database before storing real user data.
