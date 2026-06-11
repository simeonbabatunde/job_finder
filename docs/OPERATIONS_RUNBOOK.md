# Operations Runbook

Use this runbook for staging rehearsals, production launch checks, and sensitive-data operations. Keep true final submit disabled unless a separately approved pilot is active.

For the full single-VPS production deployment procedure, including DNS, Docker,
Caddy, `.env.production`, backups, health checks, updates, and rollback, see
`docs/VPS_DEPLOYMENT.md`.

## Preflight Before Staging

Run the full local gate before staging changes:

```bash
./scripts/preflight.sh
```

Expected coverage:

- Dockerized backend tests.
- Frontend lint and production build.
- Compose config rendering.
- Isolated Alembic upgrade.
- API, DB, worker, and frontend readiness checks.
- Answer-vault export/audit smoke.
- Signed-in browser dashboard smoke.

Do not proceed if this fails.

## Staging Launch

1. Set production-like staging secrets in the hosting secret manager, not in `.env`.
2. Set `APP_ENV=staging`, `USE_ALEMBIC_MIGRATIONS=true`, `ENABLE_TRUE_AUTO_SUBMIT=false`, empty `TRUE_SUBMIT_PILOT_USER_EMAILS`/`TRUE_SUBMIT_PILOT_ATS_TYPES`, and HTTPS-only `FRONTEND_URL`/`CORS_ALLOWED_ORIGINS`.
3. Deploy API and worker together so Alembic startup locking protects migration order.
4. Verify `/health`, `/health/db`, and `/health/worker`.
5. Register a staging-only user and verify resume upload, preferences save, application answers save/export/audit, dashboard load, and account export.
6. Confirm structured logs include `agent_worker.started` and no unexpected `agent_run.failed` events.

## Backup Restore Rehearsal

Before storing real resumes or application answers, prove restore with a copy of the database.

Managed Postgres:

1. Create a provider snapshot of staging or a sanitized production copy.
2. Restore it into a disposable database instance.
3. Point a staging API/worker pair at the disposable restore.
4. Run Alembic upgrade with `USE_ALEMBIC_MIGRATIONS=true`.
5. Verify `/health/db` reports `migration_mode: "alembic"`.
6. Smoke-test login, resume upload, preferences, application answers export/audit, account export, package download, and artifact access.
7. Destroy the disposable restore after verification.

Local Compose rehearsal:

```bash
mkdir -p backups
docker compose exec db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/jobmatchhero.backup
docker cp jobmatchhero-db-1:/tmp/jobmatchhero.backup backups/jobmatchhero.backup
docker compose exec db createdb -U "$POSTGRES_USER" jobmatchhero_restore_check
docker cp backups/jobmatchhero.backup jobmatchhero-db-1:/tmp/jobmatchhero.backup
docker compose exec db pg_restore -U "$POSTGRES_USER" -d jobmatchhero_restore_check --clean --if-exists /tmp/jobmatchhero.backup
docker compose exec db dropdb -U "$POSTGRES_USER" jobmatchhero_restore_check
```

Backup artifacts are private data. Do not commit or attach them to tickets.

Legacy local databases created before the JobMatchHero rebrand may still live
under pre-rebrand database, project, or volume names. Back up that data before
changing `POSTGRES_DB`, `DATABASE_URL`, `COMPOSE_PROJECT_NAME`, or the root
folder name. Restore into `jobmatchhero` after the rename if you need to
preserve local records.

## Account Export Handling

`GET /account/export` is a backend-only portability and support tool; it is not linked from the primary app UI.

Operational rules:

- Treat account-export JSON as private user data.
- If support must generate an export, confirm the requester owns the account before sharing anything.
- Share exports only through an approved secure channel.
- Do not paste export JSON into chat, issue trackers, logs, or analytics.
- Delete temporary local export files after the support case closes.
- Confirm answer-vault export access is audited without answer values.

## Answer-Vault Key Rotation

Use this when rotating `APP_DATA_ENCRYPTION_KEY`.

1. Take a verified backup or provider snapshot.
2. Move the old `APP_DATA_ENCRYPTION_KEY` into `APP_DATA_PREVIOUS_ENCRYPTION_KEYS`.
3. Set a new strong `APP_DATA_ENCRYPTION_KEY`.
4. Deploy API and worker.
5. Run a dry run:

```bash
docker compose exec -T backend uv run python -m app.jobs.reencrypt_application_answers --dry-run
```

6. If `unreadable_records` is not `0`, stop and investigate before applying.
7. Apply re-encryption:

```bash
docker compose exec -T backend uv run python -m app.jobs.reencrypt_application_answers --apply
```

8. Run the dry run again and confirm `previous_key_records`, `plaintext_records`, and `unreadable_records` are all `0`.
9. Remove old `APP_DATA_PREVIOUS_ENCRYPTION_KEYS` only after the clean post-apply dry run and backup verification.

## Operational Logging

Structured events are emitted as JSON lines through `app.observability.log_event`. They intentionally avoid resume text, answer values, tokens, and raw URLs.

Useful event families:

- `agent_run.*`: queue, start, claim, complete, failure, stale timeout.
- `agent_worker.*`: worker start, claim, completion, failure, heartbeat failure.
- `agent_node.*`: search, pre-screen, analysis, application readiness, browser-fill batches.
- `browser_fill_review.*`: API fill-review request/completion.
- `submit_readiness.*` and `submit_confirmation.*`: final-review readiness and no-click confirmation preparation.
- `auto_apply_attempt.*`: persisted attempt steps and state transitions.

Set `STRUCTURED_LOG_LEVEL` only when the hosting logger needs a different verbosity.

## True-Submit Pilot Gate

Do not enable true-submit behavior for normal staging or demos. If a controlled pilot is explicitly approved:

1. Keep `require_human_confirmation=true` in user submission settings.
2. Set `ENABLE_TRUE_AUTO_SUBMIT=true` only in the target pilot environment.
3. Add the approved users to `TRUE_SUBMIT_PILOT_USER_EMAILS`.
4. Optionally limit ATS scope with `TRUE_SUBMIT_PILOT_ATS_TYPES`, for example `greenhouse,lever`.
5. Confirm non-pilot users still see the submission guardrail as locked.
6. Confirm `POST /applications/{app_id}/submit-confirmation` still returns `can_submit=false` until a separate final-click endpoint is deliberately implemented.
7. Roll back immediately by setting `ENABLE_TRUE_AUTO_SUBMIT=false`.

## Rollback Notes

- If API startup fails in staging, verify secret strength, CORS origins, and `APP_DATA_ENCRYPTION_KEY` first.
- If `/health/worker` is degraded, inspect `agent_worker.*` events and worker heartbeat rows before queueing more runs.
- If a migration fails, restore the latest verified backup into a disposable environment before touching production data.
- If answer-vault re-encryption reports unreadable rows, keep previous keys configured and do not remove old key material until those rows are resolved.
