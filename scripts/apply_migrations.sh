#!/usr/bin/env bash
# Apply pending SQL migrations in sql/migrations/ (ordered by filename).
#
# Usage:
#   ./scripts/apply_migrations.sh "postgresql://alex@HOST:5432/alex"
#   DELTAX_DATABASE_URL=postgresql://... ./scripts/apply_migrations.sh
#
# Skips files whose version (filename without .sql) is already recorded in
# deltax_schema_migrations. Each migration must insert its version on success.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MIGRATIONS_DIR="${ROOT}/sql/migrations"
DB_URL="${1:-${DELTAX_DATABASE_URL:-}}"

if [[ -z "$DB_URL" ]]; then
  echo "Usage: $0 DATABASE_URL   (or set DELTAX_DATABASE_URL)" >&2
  exit 1
fi

log() { printf '%s\n' "$*"; }

# Ensure tracking table exists (idempotent).
psql "$DB_URL" -v ON_ERROR_STOP=1 -f "${MIGRATIONS_DIR}/001_schema_migrations.sql" >/dev/null

applied=0
skipped=0
for file in "${MIGRATIONS_DIR}"/*.sql; do
  [[ -f "$file" ]] || continue
  version="$(basename "$file" .sql)"
  if [[ "$version" == "001_schema_migrations" ]]; then
    continue
  fi
  exists="$(psql "$DB_URL" -tAc \
    "SELECT 1 FROM deltax_schema_migrations WHERE version = '${version}'" 2>/dev/null || echo "")"
  if [[ "$exists" == "1" ]]; then
    log "skip  $version (already applied)"
    skipped=$((skipped + 1))
    continue
  fi
  log "apply $version"
  psql "$DB_URL" -v ON_ERROR_STOP=1 -f "$file"
  applied=$((applied + 1))
done

log "Done — applied=$applied skipped=$skipped"
