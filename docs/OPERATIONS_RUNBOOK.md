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
docker compose exec db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/jobmatchkit.backup
docker cp jobmatchkit-db-1:/tmp/jobmatchkit.backup backups/jobmatchkit.backup
docker compose exec db createdb -U "$POSTGRES_USER" jobmatchkit_restore_check
docker cp backups/jobmatchkit.backup jobmatchkit-db-1:/tmp/jobmatchkit.backup
docker compose exec db pg_restore -U "$POSTGRES_USER" -d jobmatchkit_restore_check --clean --if-exists /tmp/jobmatchkit.backup
docker compose exec db dropdb -U "$POSTGRES_USER" jobmatchkit_restore_check
```

Backup artifacts are private data. Do not commit or attach them to tickets.

Legacy local databases created before the JobMatchKit rebrand may still live
under pre-rebrand database, project, or volume names. Back up that data before
changing `POSTGRES_DB`, `DATABASE_URL`, `COMPOSE_PROJECT_NAME`, or the root
folder name. Restore into `jobmatchkit` after the rename if you need to
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
- `agent_node.*`: search, pre-screen, analysis, and application readiness.
- `application_package.*`: package generation events where emitted.
- Retired browser automation routes should return `410 Gone` and should not emit new fill/submit workflow events.

Set `STRUCTURED_LOG_LEVEL` only when the hosting logger needs a different verbosity.

## Retired Browser Automation

Browser form filling and final-submit preparation are not part of the supported product. For staging and production checks:

1. Confirm no Apply with assistant, Application Prep, screenshot, trace, readiness, or final-confirmation controls are visible in the UI.
2. Confirm `/agent/run?auto_apply=true` returns `410 Gone`.
3. Confirm retired application-prep and submit-confirmation routes return `410 Gone`.
4. Keep any historical fill-review/automation records private and treat them as compatibility data only.

## Rollback Notes

- If API startup fails in staging, verify secret strength, CORS origins, and `APP_DATA_ENCRYPTION_KEY` first.
- If `/health/worker` is degraded, inspect `agent_worker.*` events and worker heartbeat rows before queueing more runs.
- If a migration fails, restore the latest verified backup into a disposable environment before touching production data.
- If answer-vault re-encryption reports unreadable rows, keep previous keys configured and do not remove old key material until those rows are resolved.
