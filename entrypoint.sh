#!/bin/bash
# ─── Loop Engineering unified entrypoint ─────────────────────
# Starts: nginx (static UI :80), uvicorn (FastAPI :8011), health server (:8081)

set -e

# Ensure all files/dirs created by this container are world-writable
# so OpenHands (UID 1000) can access project dirs on shared volume
umask 0000
umask 0 # belt-and-suspenders

export PYTHONPATH="/app:${PYTHONPATH:-}"

# ── Health server (port 8081) — background process ───────────
# Runs as a separate Python process so it stays alive and responds to healthchecks.
python3 /app/service/health.py &
echo "[Entrypoint] Health server started on :8081"

# ── Nginx (static frontend, port 80) ─────────────────────────
# Run as daemon so uvicorn stays in foreground (PID 1)
nginx -g 'daemon on;'
echo "[Entrypoint] Nginx started on :80"

# ── Uvicorn (FastAPI backend, port 8011) — foreground ─────────
exec uvicorn frontend.backend.app:app --host 0.0.0.0 --port 8011
