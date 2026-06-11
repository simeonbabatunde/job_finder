#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-.env.production}"

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE. Run this from the production checkout or set ENV_FILE." >&2
  exit 1
fi

env_value() {
  local key="$1"
  awk -F= -v key="$key" '
    $1 == key {
      sub(/^[^=]*=/, "")
      gsub(/^"|"$/, "")
      print
      exit
    }
  ' "$ENV_FILE"
}

postgres_user="${POSTGRES_USER:-$(env_value POSTGRES_USER)}"
postgres_db="${POSTGRES_DB:-$(env_value POSTGRES_DB)}"
backup_dir="${BACKUP_DIR:-$(env_value BACKUP_DIR)}"
retention_days="${BACKUP_RETENTION_DAYS:-$(env_value BACKUP_RETENTION_DAYS)}"
passphrase="${BACKUP_ENCRYPTION_PASSPHRASE:-$(env_value BACKUP_ENCRYPTION_PASSPHRASE)}"
r2_remote="${R2_RCLONE_REMOTE:-$(env_value R2_RCLONE_REMOTE)}"

backup_dir="${backup_dir:-backups}"
retention_days="${retention_days:-14}"

if [ -z "$postgres_user" ] || [ -z "$postgres_db" ]; then
  echo "POSTGRES_USER and POSTGRES_DB are required in $ENV_FILE." >&2
  exit 1
fi

mkdir -p "$backup_dir"

timestamp="$(date -u +"%Y%m%dT%H%M%SZ")"
backup_file="${backup_dir}/jobmatchhero-${postgres_db}-${timestamp}.dump"
final_file="$backup_file"
compose=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")

"${compose[@]}" exec -T db pg_dump -U "$postgres_user" -d "$postgres_db" -Fc > "$backup_file"

if [ -n "$passphrase" ]; then
  encrypted_file="${backup_file}.enc"
  BACKUP_ENCRYPTION_PASSPHRASE="$passphrase" \
    openssl enc -aes-256-cbc -salt -pbkdf2 -in "$backup_file" -out "$encrypted_file" -pass env:BACKUP_ENCRYPTION_PASSPHRASE
  rm -f "$backup_file"
  final_file="$encrypted_file"
fi

if [ -n "$r2_remote" ]; then
  if ! command -v rclone >/dev/null 2>&1; then
    echo "R2_RCLONE_REMOTE is set, but rclone is not installed." >&2
    exit 1
  fi
  rclone copy "$final_file" "$r2_remote"
fi

find "$backup_dir" -type f \( -name "*.dump" -o -name "*.dump.enc" \) -mtime "+${retention_days}" -print -delete

echo "Backup complete: ${final_file}"
