#!/bin/bash
set -e

echo "⏳ Waiting for DB"
until pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER"; do
  sleep 1
done
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  echo "📦 Applying migrations"
  alembic upgrade head
fi

echo "🚀 Start App"
exec "$@"