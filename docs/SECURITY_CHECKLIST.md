# Security Checklist

Use this checklist before sharing the project or deploying staging/production.

## Local Secrets

- Keep `.env` private. It is intentionally ignored by git.
- Use `.env.example` for placeholders only; never add real provider keys there.
- Rotate any OpenAI, OpenRouter, Google, SMTP, or OAuth secret that was pasted into chat, docs, screenshots, or committed history.
- Run `git grep -n -E '(sk-[A-Za-z0-9]|OPENAI_API_KEY=.+|OPENROUTER_API_KEY=.+|GOOGLE_API_KEY=.+)'` before commits that touch config or docs. Expected matches should be variable names or blank placeholders only.

## Required Production Settings

- Set `APP_ENV=production`.
- Set a strong `AUTH_SECRET_KEY` with at least 32 random characters.
- Set a strong dedicated `APP_DATA_ENCRYPTION_KEY`; production startup rejects missing keys.
- Use `AUTH_PREVIOUS_SECRET_KEYS` only during planned key rotation.
- Use `APP_DATA_PREVIOUS_ENCRYPTION_KEYS` only during planned answer-vault data-key rotation.
- Keep browser automation and true-submit behavior disabled; retired automation routes should return `410 Gone`.
- Set `USE_ALEMBIC_MIGRATIONS=true` in staging after validating the baseline against a copy of existing data.
- Set `CORS_ALLOWED_ORIGINS` or `FRONTEND_URL` to deployed HTTPS origins only; production-like startup rejects localhost and wildcard CORS origins.
- Use provider API keys with least-privilege scopes where the provider supports scoping.

## User Data

- Treat resumes, profile data, application answers, generated packages, and any historical automation artifacts as private user data.
- Application answer-vault string fields are encrypted at rest before persistence.
- Answer-vault read/export/reset/automation-use audit rows must not store answer values.
- Run the answer-vault re-encryption job and confirm a clean dry run before removing old `APP_DATA_PREVIOUS_ENCRYPTION_KEYS`.
- Store voluntary self-ID answers separately from matching preferences.
- Default voluntary self-ID answers to `prefer_not_to_answer`.
- Do not send voluntary self-ID answers to LLM prompts for matching, scoring, or ranking.
- Provide export/delete/reset controls for saved application answers and account data.
- Confirm `GET /application-profile/export` and `GET /application-profile/audit` work for the signed-in user only.
- Confirm `GET /account/export` works for the signed-in user only and treat downloaded account-export JSON as private data.

## Browser Automation

- Browser-form automation is retired; users submit manually on employer sites.
- Retired automation/prep endpoints must return `410 Gone`.
- Do not create new browser screenshots or Playwright traces.
- Keep historical automation artifacts behind authenticated access if they exist in older local data.
- Avoid logging answer values, resume text, tokens, and provider keys.

## Deployment

- Run `./scripts/preflight.sh` before staging.
- Confirm CORS only allows the deployed frontend origin.
- Confirm Postgres credentials are not the default local values.
- Confirm `/health`, `/health/db`, and `/health/worker` are healthy.
- Confirm the worker process is running when `AGENT_RUNNER_MODE=worker`.
- Confirm backup and restore testing for the production database before storing real user data.
- Follow `docs/OPERATIONS_RUNBOOK.md` for account export handling and answer-vault key rotation.
