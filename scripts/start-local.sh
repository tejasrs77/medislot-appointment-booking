#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
PYTHON="$(pwd)/.venv/bin/python"
cd backend
"$PYTHON" -m alembic upgrade head
"$PYTHON" -m app.seed
"$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 &
API_PID=$!
trap 'kill "$API_PID"' EXIT INT TERM
cd ../frontend
npm run dev
