#!/bin/sh
set -e

DATA_DIR=/app/backend/data

# Bootstrap data on first run (skipped if DuckDB files already exist via volume)
if [ ! -f "$DATA_DIR/cijfers.duckdb" ]; then
    echo "[entrypoint] First run — downloading CBS statistics ..."
    cd /app/backend && python download_data.py --no-geo
fi

if [ ! -f "$DATA_DIR/gemeente_geo.duckdb" ]; then
    echo "[entrypoint] Building gemeente geometry ..."
    cd /app/backend && python -c "from download_data import download_geometry, compute_neighbors_spatial; download_geometry() and compute_neighbors_spatial()"
fi

# Start FastAPI in the background
echo "[entrypoint] Starting FastAPI ..."
cd /app/backend
uvicorn app:app --host 127.0.0.1 --port 8000 &

# Start nginx in the foreground (keeps container alive)
echo "[entrypoint] Starting nginx ..."
nginx -g "daemon off;"
