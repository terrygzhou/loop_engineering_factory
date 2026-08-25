#!/bin/bash
# ─── Loop Engineering unified entrypoint ─────────────────────
# Starts: nginx (static UI :4080 host → :80 container), uvicorn (FastAPI :48011 host → :8011), health server (:48081 host → :8081)

set -e

# Ensure output directory is accessible by shared containers (UID 1000)
# Use group-writable permissions instead of world-writable (chmod 777)
umask 0002
APP_UID=1000
APP_GID=1000
mkdir -p /app/output
chown -R ${APP_UID}:${APP_GID} /app/output 2>/dev/null || true
chmod -R g+rw /app/output 2>/dev/null || true

export PYTHONPATH="/app:${PYTHONPATH:-}"

# ── Health server (port 8081) — background process ───────────
# Runs as a separate Python process so it stays alive and responds to healthchecks.
python3 /app/service/health.py &
echo "[Entrypoint] Health server started on :8081 (published as :48081)"

# ── Nginx (static frontend, port 80) ─────────────────────────
# Run as daemon so uvicorn stays in foreground (PID 1)
nginx -g 'daemon on;'
echo "[Entrypoint] Nginx started on :80"

# ── Uvicorn (FastAPI backend, port 8011) — foreground ─────────
exec uvicorn frontend.backend.app:app --host 0.0.0.0 --port 8011
