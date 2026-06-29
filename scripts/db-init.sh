#!/usr/bin/env bash
# Bootstrap the database inside the running stack:
#  1. wait for postgres
#  2. generate the initial alembic revision if no migrations exist yet
#  3. apply migrations
#
# Usage:
#   ./scripts/db-init.sh           # apply existing migrations
#   ./scripts/db-init.sh --initial # generate the first revision then apply
set -euo pipefail

COMPOSE="${COMPOSE:-docker compose}"

if [ "${1:-}" = "--initial" ]; then
  echo "==> Generating initial Alembic revision"
  $COMPOSE exec backend alembic revision --autogenerate -m "initial schema"
fi

echo "==> Applying migrations"
$COMPOSE exec backend alembic upgrade head

echo "==> Database is up to date"
