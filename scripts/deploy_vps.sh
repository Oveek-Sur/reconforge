#!/usr/bin/env bash
# ReconForge — one-shot deploy on a fresh Debian/Ubuntu GCP (or any) VPS.
# Installs jadx + Python deps, generates a STRONG remote token, tunes memory,
# and binds to localhost (reach it safely with an SSH tunnel — see the end).
#
# Usage on the VPS:
#   git clone https://github.com/Oveek-Sur/reconforge && cd reconforge
#   bash scripts/deploy_vps.sh
#
# Env knobs (memory):
#   RECONFORGE_JADX_XMX=2g        # jadx heap cap (default 4g; use 2g on a 4GB VM)
#   RECONFORGE_JADX_THREADS=2     # jadx worker threads (fewer = less RAM)
#   RECONFORGE_JADX_LEAN=1        # skip debug info (less RAM/time)
#   RF_BIND=0.0.0.0               # public bind (NOT recommended — see security note)
set -e
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

echo "== 1. system packages =="
if command -v apt-get >/dev/null; then
  sudo apt-get update -y
  sudo apt-get install -y --no-install-recommends \
    openjdk-17-jre-headless python3 python3-venv python3-pip git curl unzip jadx mitmproxy || \
  sudo apt-get install -y openjdk-17-jre-headless python3 python3-venv python3-pip git curl unzip
fi
command -v jadx >/dev/null && echo "jadx: $(command -v jadx)" || echo "!! jadx not in apt — install manually from github.com/skylot/jadx/releases"

echo "== 2. python venv + deps =="
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r backend/requirements.txt

echo "== 3. strong remote token + memory-tuned config =="
mkdir -p data
TOKEN="$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')"
python3 - "$TOKEN" <<'PY'
import json, sys, pathlib
p = pathlib.Path("data/config.json")
cfg = json.loads(p.read_text()) if p.exists() else {}
cfg.setdefault("settings", {})
cfg["settings"]["remote_token"] = sys.argv[1]
cfg["settings"]["allow_sudo"] = True
p.write_text(json.dumps(cfg, indent=2))
print("config.json written")
PY

echo "== 4. memory defaults (override in the environment as needed) =="
: "${RECONFORGE_JADX_XMX:=4g}"
: "${RECONFORGE_JADX_THREADS:=$(( $(nproc) > 2 ? $(nproc)-1 : 1 ))}"
export RECONFORGE_JADX_XMX RECONFORGE_JADX_THREADS

echo "== 5. launch (bound to ${RF_BIND:-127.0.0.1}) =="
export RECONFORGE_HOST="${RF_BIND:-127.0.0.1}"
echo
echo "══════════════════════════════════════════════════════════════════"
echo " ReconForge remote token : $TOKEN"
echo " jadx heap / threads     : $RECONFORGE_JADX_XMX / $RECONFORGE_JADX_THREADS"
echo " Bound to                : ${RECONFORGE_HOST}:8777"
echo "──────────────────────────────────────────────────────────────────"
echo " SAFE ACCESS from your PC (no public exposure):"
echo "   gcloud compute ssh <vm> --zone <zone> -- -N -L 8777:localhost:8777"
echo "   then use  http://127.0.0.1:8777  on your PC"
echo "══════════════════════════════════════════════════════════════════"
echo
nohup .venv/bin/python backend/main.py > data/reconforge.log 2>&1 &
echo "started pid $! ; logs: data/reconforge.log"
