#!/bin/bash
# Production startup script for the Myntist Sovereign Beacon.
# Installs Python dependencies, starts the FastAPI backend (uvicorn) as a
# background daemon, waits until it is ready, then execs the Express API server
# in the foreground so the container lifecycle follows the Node process.

set -e

WORKSPACE=/home/runner/workspace
BEACON_DIR="${WORKSPACE}/myntist-beacon"
EXPRESS_ENTRY="${WORKSPACE}/artifacts/api-server/dist/index.mjs"
FASTAPI_PORT=8000
MAX_WAIT=60

echo "[start-production] Installing Python dependencies..."
pip install -r "${BEACON_DIR}/requirements.txt" --quiet 2>&1 | tail -5 || true

echo "[start-production] Starting FastAPI backend on port ${FASTAPI_PORT}..."
cd "${BEACON_DIR}"
uvicorn iam_substrate.substrate_api.main:app \
  --host 0.0.0.0 \
  --port "${FASTAPI_PORT}" \
  --workers 1 \
  --no-access-log \
  --log-level warning &

FASTAPI_PID=$!
echo "[start-production] FastAPI PID=${FASTAPI_PID}"

# Wait for FastAPI to be ready before starting Express
echo "[start-production] Waiting for FastAPI to be ready (max ${MAX_WAIT}s)..."
for i in $(seq 1 ${MAX_WAIT}); do
  if curl -sf "http://localhost:${FASTAPI_PORT}/health" > /dev/null 2>&1; then
    echo "[start-production] FastAPI is ready after ${i}s"
    break
  fi
  if ! kill -0 "${FASTAPI_PID}" 2>/dev/null; then
    echo "[start-production] ERROR: FastAPI process exited unexpectedly"
    exit 1
  fi
  sleep 1
done

# If FastAPI still not healthy, log a warning but continue
if ! curl -sf "http://localhost:${FASTAPI_PORT}/health" > /dev/null 2>&1; then
  echo "[start-production] WARNING: FastAPI not healthy after ${MAX_WAIT}s — starting Express anyway"
fi

echo "[start-production] Starting Express API server on PORT=${PORT}..."
exec node --enable-source-maps "${EXPRESS_ENTRY}"
