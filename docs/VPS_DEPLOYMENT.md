# VPS Deployment Guide

This guide is the production VPS path for JobMatchKit. It assumes a single
Ubuntu server running Docker Compose, with Caddy serving the frontend, proxying
API requests, and managing HTTPS certificates.

Use this route for the first real deployment. Move Postgres, workers, or
browser automation to separate services only after usage proves that the single
VPS is not enough.

## Recommended Architecture

- `web`: Caddy serving the built React app and proxying `/api/*` to the backend.
- `backend`: FastAPI on port `8000`, exposed only inside the Docker network.
- `worker`: queued matching workflow runner using `AGENT_RUNNER_MODE=worker`.
- `db`: Postgres 15 with a named Docker volume.
- `caddy_data`: named volume for Caddy certificates.
- Cloudflare DNS in front of the VPS.
- Daily encrypted Postgres backups copied to Cloudflare R2, S3, or another
  off-server storage location.

## VPS Options

Verify current pricing in the provider console before purchasing; VPS prices and
regional availability change often.

| Provider | Good starting size | Why use it |
| --- | --- | --- |
| Hetzner Cloud | 2 vCPU / 4 GB minimum, 4 vCPU / 8 GB preferred | Best price/performance when available. Good fit for a cost-sensitive first deployment. |
| Vultr | 2 vCPU / 4 GB / 80 GB | Good US region coverage and simple VPS operations. |
| DigitalOcean | Basic 2 vCPU / 4 GB / 80 GB | Beginner-friendly dashboard and strong docs, but usually more expensive. |
| AWS Lightsail | Linux 2 vCPU / 4 GB / 80 GB | Useful if you want AWS account consolidation, but not the best value for this app. |

Start with 4 GB RAM only if traffic is low and add swap. Prefer 8 GB RAM if you
expect larger matching batches or multiple users.

## LLM Recommendation

The production default should be reliable before it is maximally cheap:

```text
LLM_PROVIDER=openai
OPENAI_MODEL=gpt-5-mini
```

Cost-optimized alternatives:

- `LLM_PROVIDER=gemini` with `GOOGLE_MODEL=gemini-2.5-flash-lite` for very cheap
  bulk matching.
- `LLM_PROVIDER=openrouter` with `OPENROUTER_MODEL=openai/gpt-oss-120b` for
  ultra-low-cost experiments.

Do not depend on free OpenRouter variants for production reliability.

## 1. Buy And Point The Domain

Use Cloudflare DNS. Add these records after the VPS is created:

```text
A      @      <VPS_PUBLIC_IP>
CNAME  www    <root-domain>
```

If you want both root and `www`, set `APP_DOMAIN` in `.env.production` to both
hostnames:

```text
APP_DOMAIN=jobmatchkit.com,www.jobmatchkit.com
```

## 2. Provision The VPS

Choose Ubuntu 24.04 LTS, SSH-key login, and no password login. Open only:

```text
22/tcp
80/tcp
443/tcp
```

Initial server hardening:

```bash
sudo apt update
sudo apt upgrade -y
sudo adduser deploy
sudo usermod -aG sudo deploy
sudo ufw allow OpenSSH
sudo ufw allow 80
sudo ufw allow 443
sudo ufw enable
```

Then reconnect as `deploy`.

Optional but recommended on 4 GB VPS instances:

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## 3. Install Docker

Install Docker using Docker's official Ubuntu instructions, then verify:

```bash
docker --version
docker compose version
```

Allow the deploy user to run Docker:

```bash
sudo usermod -aG docker deploy
```

Log out and back in so the group change applies.

## 4. Clone The Repo

```bash
git clone https://github.com/simeonbabatunde/jobmatchkit.git jobmatchkit
cd jobmatchkit
```

## 5. Create Production Secrets

Copy the template:

```bash
cp .env.production.example .env.production
chmod 600 .env.production
```

Generate strong secrets:

```bash
openssl rand -base64 48
openssl rand -base64 48
openssl rand -base64 32
```

Fill `.env.production` with real values:

```text
APP_DOMAIN=jobmatchkit.com
FRONTEND_URL=https://jobmatchkit.com
CORS_ALLOWED_ORIGINS=https://jobmatchkit.com
VITE_API_URL=/api

POSTGRES_USER=jobmatchkit
POSTGRES_PASSWORD=<long random password>
POSTGRES_DB=jobmatchkit
DATABASE_URL=postgresql://jobmatchkit:<long random password>@db:5432/jobmatchkit

APP_ENV=production
AUTH_SECRET_KEY=<32+ random characters>
APP_DATA_ENCRYPTION_KEY=<32+ random characters>
USE_ALEMBIC_MIGRATIONS=true
AGENT_RUNNER_MODE=worker
ENABLE_TRUE_AUTO_SUBMIT=false

STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRO_PRICE_ID=price_...
PRO_PLAN_PRICE_LABEL=$10/mo
BILLING_SUCCESS_URL=https://jobmatchkit.com/settings?billing=success
BILLING_CANCEL_URL=https://jobmatchkit.com/settings?billing=cancelled
BILLING_PORTAL_RETURN_URL=https://jobmatchkit.com/settings?billing=portal_return

LLM_PROVIDER=openai
OPENAI_MODEL=gpt-5-mini
OPENAI_API_KEY=
```

Do not commit `.env.production`. It is intentionally ignored by git.

## 6. OAuth Redirect URLs

If Google or LinkedIn OAuth is enabled, use the same-origin `/api` callback URLs
because Caddy strips `/api` before forwarding to FastAPI:

```text
GOOGLE_REDIRECT_URI=https://jobmatchkit.com/api/auth/google/callback
LINKEDIN_REDIRECT_URI=https://jobmatchkit.com/api/auth/linkedin/callback
```

Register the exact same URLs in each provider dashboard.


## 7. Stripe Billing Setup

Create one Stripe product for JobMatchKit Pro and one recurring monthly price for
`$10/month`. Copy the Stripe price ID into `STRIPE_PRO_PRICE_ID`. Use live keys
only in production and test keys locally.

Create a webhook endpoint in Stripe pointing to:

```text
https://jobmatchkit.com/api/billing/webhook
```

Subscribe the endpoint to these events:

```text
checkout.session.completed
customer.subscription.created
customer.subscription.updated
customer.subscription.deleted
invoice.paid
invoice.payment_failed
```

Copy the webhook signing secret into `STRIPE_WEBHOOK_SECRET`. The app treats
Stripe webhooks as the billing source of truth; returning from Checkout alone
does not permanently upgrade the account.

## 8. First Deploy

Use the helper script:

```bash
./scripts/deploy-prod.sh
```

Or run the equivalent commands manually:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml build
docker compose --env-file .env.production -f docker-compose.prod.yml up -d
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

The backend runs Alembic startup migrations when
`USE_ALEMBIC_MIGRATIONS=true`. The API and worker can start together because the
startup migration path takes a Postgres advisory lock.

## 9. Verify Health

Internal checks from the VPS:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T backend curl -fsS http://localhost:8000/health
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T backend curl -fsS http://localhost:8000/health/db
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T backend curl -fsS http://localhost:8000/health/worker
```

Public checks after DNS and HTTPS are ready:

```bash
curl https://jobmatchkit.com/api/health
curl https://jobmatchkit.com/api/health/db
curl https://jobmatchkit.com/api/health/worker
```

`/api/health/worker` should be healthy when the worker heartbeat is fresh.

## 10. Backups

Create a backup:

```bash
./scripts/backup-postgres.sh
```

Recommended settings in `.env.production` or the shell:

```text
BACKUP_DIR=backups
BACKUP_RETENTION_DAYS=14
BACKUP_ENCRYPTION_PASSPHRASE=<strong passphrase>
R2_RCLONE_REMOTE=cloudflare-r2:jobmatchkit-db-backups
```

For off-server uploads, install and configure `rclone` for Cloudflare R2 or S3.
Run the backup script from cron:

```cron
15 3 * * * cd /home/deploy/jobmatchkit && /home/deploy/jobmatchkit/scripts/backup-postgres.sh >> /home/deploy/jobmatchkit/backups/backup.log 2>&1
```

Backup retention target:

- Daily backups retained 14 days.
- Weekly backups retained 8 weeks.
- Monthly backups retained 12 months.
- Restore rehearsal at least monthly.

## 11. Restore Rehearsal

Never let the first restore test be a real incident.

For an unencrypted local backup, copy the dump into the database container and
restore it into a disposable database. Replace `jobmatchkit` if your
`POSTGRES_USER` differs:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml cp backups/<backup-file>.dump db:/tmp/jobmatchkit.restore.dump
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T db createdb -U jobmatchkit jobmatchkit_restore_check
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T db pg_restore -U jobmatchkit -d jobmatchkit_restore_check --clean --if-exists /tmp/jobmatchkit.restore.dump
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T db dropdb -U jobmatchkit jobmatchkit_restore_check
```

For encrypted backups, decrypt first on a secure machine:

```bash
openssl enc -d -aes-256-cbc -pbkdf2 -in backup.dump.enc -out backup.dump
```

Then copy the dump into the database container and run `pg_restore`.

## 12. Updating Production

```bash
cd /home/deploy/jobmatchkit
git pull
./scripts/deploy-prod.sh
```

After deploy:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=100 backend
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=100 worker
```

## 13. Rollback

Fast rollback to the previous Git commit:

```bash
git log --oneline -5
git checkout <previous-good-sha>
./scripts/deploy-prod.sh
```

If the rollback crosses database migrations, restore a verified backup into a
disposable environment first and confirm the old code can read it.

## 14. Monitoring

Minimum monitoring:

- Uptime monitor for `https://jobmatchkit.com/api/health`.
- Uptime monitor for `https://jobmatchkit.com/api/health/db`.
- Alert if `/api/health/worker` returns 503 for more than a few minutes.
- Disk usage alert before 80%.
- Backup success/failure alert.
- LLM provider monthly budget limit and alert.

Useful production commands:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml ps
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f backend
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f worker
docker system df
df -h
```

## 15. Scale Later

Move pieces only when there is evidence:

- Move Postgres to managed Postgres when backup/restore, uptime, or disk risk
  becomes more important than cost.
- Move `worker` to a separate VPS when browser automation or matching runs compete
  with API latency.
- Add Redis/queue infrastructure only after the persisted database queue becomes
  a bottleneck.
