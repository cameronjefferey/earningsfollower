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

# Prefer Homebrew Python 3.10+; macOS /usr/bin/python3 is still 3.9 and
# breaks SQLAlchemy Mapped[str | None] annotations.
resolve_python() {
  local candidate
  for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      local ver
      ver="$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
      if [ "$(printf '%s\n' "$ver" "3.10" | sort -V | head -n1)" = "3.10" ]; then
        echo "$candidate"
        return 0
      fi
    fi
  done
  echo "Need Python 3.10+ (found only $(command -v python3 || true)). Try: brew install python@3.13" >&2
  exit 1
}

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
    PY_CMD="$(resolve_python)"
    echo "==> Creating backend virtualenv with $PY_CMD ($($PY_CMD --version))"
    "$PY_CMD" -m venv "$VENV"
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
