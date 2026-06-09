#!/usr/bin/env bash
# Convenience runner for earningsfollower.
#
# Usage:
#   ./run.sh setup            # create venv + install backend & frontend deps
#   ./run.sh refresh [args]   # refresh data (passes extra args to app.refresh)
#   ./run.sh api              # start the FastAPI backend on :8000
#   ./run.sh web              # start the Next.js frontend on :3000
#
# Examples:
#   ./run.sh refresh --tickers NVDA,SNOW,ORCL --no-peers
#   ./run.sh refresh                       # full universe

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
VENV="$BACKEND/.venv"
PY="$VENV/bin/python"

ensure_venv() {
  if [ ! -x "$PY" ]; then
    echo "No virtualenv found. Run: ./run.sh setup" >&2
    exit 1
  fi
}

cmd="${1:-help}"
shift || true

case "$cmd" in
  setup)
    echo "==> Creating backend virtualenv"
    python3 -m venv "$VENV"
    "$PY" -m pip install --upgrade pip
    "$PY" -m pip install -r "$BACKEND/requirements.txt"
    [ -f "$BACKEND/.env" ] || cp "$BACKEND/.env.example" "$BACKEND/.env"
    echo "==> Installing frontend deps"
    (cd "$FRONTEND" && npm install)
    [ -f "$FRONTEND/.env.local" ] || cp "$FRONTEND/.env.local.example" "$FRONTEND/.env.local"
    echo "==> Done. Next: ./run.sh refresh   then   ./run.sh api   (and ./run.sh web)"
    ;;

  refresh)
    ensure_venv
    (cd "$BACKEND" && "$PY" -m app.refresh "$@")
    ;;

  api)
    ensure_venv
    echo "==> API on http://127.0.0.1:8000  (docs at /docs)"
    (cd "$BACKEND" && "$VENV/bin/uvicorn" app.main:app --reload --port 8000)
    ;;

  web)
    echo "==> Web on http://localhost:3000"
    (cd "$FRONTEND" && npm run dev)
    ;;

  *)
    sed -n '2,12p' "$ROOT/run.sh"
    ;;
esac
