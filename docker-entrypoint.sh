#!/bin/sh
set -e
echo "running alembic migrations"
alembic upgrade head
exec uvicorn src.main:app --host 0.0.0.0 --port "${PORT:-8000}"
