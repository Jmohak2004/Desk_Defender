#!/usr/bin/env bash
# Desk Defender launcher (macOS).
#   ./start.sh            backend (:8000) + Vite dev frontend (:5173)
#   ./start.sh --prod     build the frontend once and serve everything from the backend on :8000
#   ./start.sh --sim      use the clearly-labelled SIMULATED camera (development / no hardware)
#   ./start.sh --setup    only create the venv and install dependencies
set -euo pipefail
cd "$(dirname "$0")"

MODE=dev
SIM=0
SETUP_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --prod) MODE=prod ;;
    --sim) SIM=1 ;;
    --setup) SETUP_ONLY=1 ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg"; exit 1 ;;
  esac
done

pick_python() {
  for py in python3.12 python3.11 python3.13 python3; do
    if command -v "$py" >/dev/null 2>&1; then
      if "$py" -c 'import sys; sys.exit(0 if (3, 11) <= sys.version_info[:2] <= (3, 13) else 1)'; then
        echo "$py"; return
      fi
    fi
  done
  echo "ERROR: Python 3.11-3.13 is required (brew install python@3.12)" >&2
  exit 1
}

if [ ! -x venv/bin/python ]; then
  PY=$(pick_python)
  echo "==> Creating virtual environment with $PY"
  "$PY" -m venv venv
fi
if ! venv/bin/python -c 'import fastapi, cv2, ultralytics' >/dev/null 2>&1; then
  echo "==> Installing Python dependencies (first run can take a few minutes)"
  venv/bin/pip install --upgrade pip >/dev/null
  venv/bin/pip install -r backend/requirements.txt
fi
command -v npm >/dev/null || { echo "ERROR: Node.js 18+ is required (brew install node)"; exit 1; }
# Reinstall if node_modules is missing or incomplete (e.g. an interrupted install left packages without files).
if ! (cd frontend && node -e "require.resolve('@babel/core'); require.resolve('vite'); require.resolve('react')" >/dev/null 2>&1); then
  echo "==> Installing frontend dependencies (clean)"
  rm -rf frontend/node_modules
  npm --prefix frontend ci
fi
[ "$SETUP_ONLY" = 1 ] && { echo "==> Setup complete"; exit 0; }

if [ "$SIM" = 1 ]; then
  export DESK_DEFENDER_SIMULATED=1
  echo "==> SIMULATED camera mode (development only)"
fi

PIDS=()
cleanup() {
  echo; echo "==> Stopping Desk Defender"
  for pid in "${PIDS[@]:-}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if [ "$MODE" = prod ]; then
  echo "==> Building frontend"
  npm --prefix frontend run build
  echo "==> Desk Defender on http://localhost:8000"
  (sleep 3 && open "http://localhost:8000" >/dev/null 2>&1 || true) &
  venv/bin/python -m backend.main
else
  venv/bin/python -m backend.main &
  PIDS+=($!)
  echo "==> Waiting for backend on :8000"
  for _ in $(seq 1 60); do curl -sf http://127.0.0.1:8000/api/health >/dev/null && break; sleep 0.5; done
  echo "==> Desk Defender on http://localhost:5173"
  (sleep 2 && open "http://localhost:5173" >/dev/null 2>&1 || true) &
  npm --prefix frontend run dev -- --port 5173 --strictPort &
  PIDS+=($!)
  wait
fi
