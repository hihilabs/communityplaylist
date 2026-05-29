#!/bin/bash
set -e

CONTAINER="cp-local-cp-local-1"
FRONTEND_DIR="$(dirname "$0")/frontend"

echo "==> Building frontend..."
cd "$FRONTEND_DIR" && npm run build

echo "==> Collecting static files..."
docker exec "$CONTAINER" python manage.py collectstatic --noinput --clear

echo "==> Reloading gunicorn workers..."
docker exec "$CONTAINER" sh -c 'kill -HUP $(cat /tmp/gunicorn.pid 2>/dev/null || ls /proc/*/exe 2>/dev/null | while read f; do t=$(readlink "$f" 2>/dev/null); [ "$t" != "${t#*/gunicorn}" ] && echo "${f%/exe}" | grep -o "[0-9]*"; done | head -1)' 2>/dev/null || (docker restart "$CONTAINER" && sleep 3 && docker exec "$CONTAINER" python manage.py collectstatic --noinput --clear)

echo "==> Done. Hard-refresh the browser (Ctrl+Shift+R) to see changes."
