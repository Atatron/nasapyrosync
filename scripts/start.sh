#!/usr/bin/env bash
# PyroSync launcher for macOS and Linux.
# First run: creates .venv, installs the tested Python packages, then starts the local server.
# Usage: ./scripts/start.sh            (then open http://127.0.0.1:8000)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY=""
for c in python3.13 python3.12 python3.11 python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "PyroSync needs Python 3.11 or newer. Install it from https://www.python.org/downloads/ and run this script again." >&2
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "Creating virtual environment (.venv) with $($PY --version)…"
  "$PY" -m venv .venv
fi
VPY="$ROOT/.venv/bin/python"

STAMP=".venv/.pyrosync-deps"
WANT="$(cat backend/requirements.lock.txt backend/requirements.txt | cksum)"
if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$WANT" ]; then
  echo "Installing Python packages (first run can take a few minutes)…"
  "$VPY" -m pip install --upgrade pip >/dev/null
  if ! "$VPY" -m pip install -r backend/requirements.lock.txt; then
    echo "Exact tested versions are not available for this Python; installing compatible versions instead…"
    "$VPY" -m pip install -r backend/requirements.txt
  fi
  echo "$WANT" > "$STAMP"
fi

if [ ! -f frontend/dist/index.html ]; then
  if command -v npm >/dev/null 2>&1; then
    echo "Building the web interface…"
    (cd frontend && npm ci && npm run build)
  else
    echo "frontend/dist is missing and Node.js/npm is not installed. Install Node.js 20.19+ or 22.12+ from https://nodejs.org, or use a release package that includes frontend/dist." >&2
    exit 1
  fi
fi

[ -f .env ] || cp .env.example .env
cd backend
echo "Starting PyroSync on http://${PYROSYNC_HOST:-127.0.0.1}:${PYROSYNC_PORT:-8000}  (Ctrl+C to stop)"
exec "$VPY" -m pyrosync.cli serve "$@"
