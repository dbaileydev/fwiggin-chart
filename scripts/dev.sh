#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

API_PID=""
WEB_PID=""

cleanup() {
  trap - INT TERM EXIT
  if [[ -n "$API_PID" ]]; then
    kill "$API_PID" 2>/dev/null || true
  fi
  if [[ -n "$WEB_PID" ]]; then
    kill "$WEB_PID" 2>/dev/null || true
  fi
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

if [[ ! -x api/.venv/bin/uvicorn ]]; then
  echo "API venv missing. Run:"
  echo "  python3 -m venv api/.venv"
  echo "  api/.venv/bin/pip install -r api/requirements.txt -r requirements.txt"
  exit 1
fi

if [[ ! -d web/node_modules ]]; then
  echo "Frontend deps missing. Run: cd web && npm install"
  exit 1
fi

api/.venv/bin/uvicorn api.main:app --reload --host 127.0.0.1 --port 8000 &
API_PID=$!

(cd web && npm run dev) &
WEB_PID=$!

echo ""
echo "Backtester running:"
echo "  API → http://127.0.0.1:8000"
echo "  UI  → http://localhost:5173"
echo ""
echo "Press Ctrl+C to stop both."
echo ""

wait "$API_PID" "$WEB_PID" 2>/dev/null || wait
