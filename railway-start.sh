#!/bin/bash
# Single-container process supervisor for Railway: runs Redis, the Celery
# worker, and the API together since Railway can't share a volume/filesystem
# across separate services (local dev instead uses docker-compose.yml, three
# containers sharing a bind-mounted ./downloads directory).
set -uo pipefail

export SSL_CERT_FILE="${SSL_CERT_FILE:-$(python3 -c 'import certifi; print(certifi.where())')}"
export REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/0}"

redis-server --save "" --appendonly no --bind 127.0.0.1 &
REDIS_PID=$!

echo "waiting for redis..."
tries=0
until python3 -c "import redis; redis.Redis(host='127.0.0.1', port=6379).ping()" 2>/dev/null; do
  tries=$((tries + 1))
  if [ "$tries" -ge 100 ]; then
    echo "redis never became ready, exiting" >&2
    exit 1
  fi
  sleep 0.3
done
echo "redis ready"

# concurrency=1: this container's whole memory budget is shared with Redis
# and Uvicorn, and an H.264 transcode can spike memory — two at once risks
# an OOM kill more than the sequential wait is worth here.
celery -A app.celery_app worker --loglevel=info --concurrency=1 &
WORKER_PID=$!

uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" &
API_PID=$!

cleanup() {
  kill -TERM "$REDIS_PID" "$WORKER_PID" "$API_PID" 2>/dev/null
  wait 2>/dev/null
}
trap cleanup TERM INT

# Exit (and let Railway restart the container) as soon as any one process dies.
wait -n "$REDIS_PID" "$WORKER_PID" "$API_PID"
EXIT_CODE=$?
cleanup
exit "$EXIT_CODE"
