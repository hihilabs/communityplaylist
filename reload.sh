#!/bin/bash
set -e

CONTAINER="cp-local-cp-local-1"
FRONTEND_DIR="$(dirname "$0")/frontend"

echo "==> Building frontend..."
cd "$FRONTEND_DIR" && npm run build

echo "==> Collecting static files..."
docker exec "$CONTAINER" python manage.py collectstatic --noinput --clear

echo "==> Done. Hard-refresh the browser to see changes."
