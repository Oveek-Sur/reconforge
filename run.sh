#!/usr/bin/env bash
# ReconForge launcher for Kali/Linux.
#   - auto-pulls latest from GitHub if this is a git checkout
#   - first run creates a venv + installs deps
#   - RECONFORGE_RELOAD=1 bash run.sh  → hot-reload (picks up `git pull` instantly)
set -e
cd "$(dirname "$0")"

if [ -d .git ]; then
  echo "[reconforge] updating from GitHub…"
  git pull --ff-only origin main || echo "[reconforge] git pull skipped (local changes / offline)"
fi

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r backend/requirements.txt

echo "─────────────────────────────────────────────"
echo " ReconForge → http://127.0.0.1:8777"
echo "─────────────────────────────────────────────"
if [ "${RECONFORGE_RELOAD:-0}" = "1" ]; then
  cd backend && exec uvicorn main:app --host "${RECONFORGE_HOST:-127.0.0.1}" --port 8777 --reload
else
  exec python backend/main.py
fi
