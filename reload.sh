#!/bin/bash
set -e

CONTAINER="cp-local-cp-local-1"
FRONTEND_DIR="$(dirname "$0")/frontend"

echo "==> Building frontend..."
cd "$FRONTEND_DIR" && npm run build

echo "==> Collecting static files..."
docker exec "$CONTAINER" python manage.py collectstatic --noinput --clear

echo "==> Reloading gunicorn workers..."
docker exec "$CONTAINER" pkill -HUP -f gunicorn

echo "==> Done. Hard-refresh the browser (Ctrl+Shift+R) to see changes."
