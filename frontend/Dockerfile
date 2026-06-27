# ─── Stage 1: Build Python dependencies ─────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ─── Stage 2: Runtime with nginx + uvicorn ───────────────────
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends nginx && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy backend app
COPY backend/ ./backend/

# Copy static frontend files and fix permissions
COPY static/ /usr/share/nginx/html/
RUN chmod -R 755 /usr/share/nginx/html/

# Configure nginx
COPY nginx/nginx.conf /etc/nginx/sites-available/default
RUN rm -f /etc/nginx/sites-enabled/default && \
    ln -s /etc/nginx/sites-available/default /etc/nginx/sites-enabled/

# Create writable project directory
RUN mkdir -p /workspace/projects

# Create mount point for parent Loop Engineering project
VOLUME /loop_engineering

# Expose both nginx (80) and uvicorn (8011)
EXPOSE 80 8011

# Start nginx and uvicorn backend
# PYTHONPATH added via environment in docker-compose.yml
CMD ["sh", "-c", "nginx -g 'daemon off;' & uvicorn backend.app:app --host 0.0.0.0 --port 8011 --app-dir /app"]
