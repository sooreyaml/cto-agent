#!/bin/sh
set -eu

MIGRATION_MAX_ATTEMPTS="${MIGRATION_MAX_ATTEMPTS:-12}"
MIGRATION_RETRY_SECONDS="${MIGRATION_RETRY_SECONDS:-5}"

case "$MIGRATION_MAX_ATTEMPTS" in
  ''|*[!0-9]*) echo "MIGRATION_MAX_ATTEMPTS must be a positive integer" >&2; exit 1 ;;
esac
case "$MIGRATION_RETRY_SECONDS" in
  ''|*[!0-9]*) echo "MIGRATION_RETRY_SECONDS must be a non-negative integer" >&2; exit 1 ;;
esac
if [ "$MIGRATION_MAX_ATTEMPTS" -lt 1 ]; then
  echo "MIGRATION_MAX_ATTEMPTS must be at least 1" >&2
  exit 1
fi

attempt=1
while [ "$attempt" -le "$MIGRATION_MAX_ATTEMPTS" ]; do
  echo "running alembic migrations (attempt $attempt/$MIGRATION_MAX_ATTEMPTS)"
  if alembic upgrade head; then
    echo "alembic migrations complete"
    break
  fi
  if [ "$attempt" -eq "$MIGRATION_MAX_ATTEMPTS" ]; then
    echo "alembic migrations failed after $MIGRATION_MAX_ATTEMPTS attempts" >&2
    exit 1
  fi
  echo "migration attempt failed; retrying in ${MIGRATION_RETRY_SECONDS}s" >&2
  sleep "$MIGRATION_RETRY_SECONDS"
  attempt=$((attempt + 1))
done

exec uvicorn src.main:app --host 0.0.0.0 --port "${PORT:-8000}"
