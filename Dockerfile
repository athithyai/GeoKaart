# ── Stage 1: Build React frontend ────────────────────────────────────────────
FROM node:20-alpine AS frontend-builder
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci --silent
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Production image ─────────────────────────────────────────────────
FROM python:3.12-slim

# nginx for static files + API proxy
RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx \
    && rm -rf /var/lib/apt/lists/*

# Python deps
WORKDIR /app/backend
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Backend source
COPY backend/ .

# Built frontend → nginx root
COPY --from=frontend-builder /app/dist /var/www/html

# nginx config — full nginx.conf for HF Spaces non-root (UID 1000) compatibility
COPY nginx.conf /etc/nginx/nginx.conf

# Create nginx temp dirs (writable by UID 1000) and data dir
RUN mkdir -p /tmp/nginx/client_temp \
             /tmp/nginx/proxy_temp \
             /tmp/nginx/fastcgi_temp \
             /tmp/nginx/uwsgi_temp \
             /tmp/nginx/scgi_temp \
             /app/backend/data/geometry \
    && chmod -R 777 /tmp/nginx \
    && chown -R 1000:1000 /app/backend/data \
    && chmod -R 755 /app/backend/data

# Startup script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 7860

ENTRYPOINT ["/entrypoint.sh"]
