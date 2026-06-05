#!/usr/bin/env bash
# Put ROScribe on the internet for a CLOSED user base (login-gated), via a free
# Cloudflare quick tunnel. Everything — index, PDFs, breakdown LLM — stays on
# THIS machine; only rendered results travel. Keep this terminal open to stay live.
#
#   ./scripts/serve_public.sh
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# 1. ensure a login + session secret exist (persisted in .env)
if ! grep -q '^ROSCRIBE_USERS=' .env 2>/dev/null; then
  PW=$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 10)
  echo "ROSCRIBE_USERS=laksh:${PW}" >> .env
  echo "ROSCRIBE_STORAGE_SECRET=$(LC_ALL=C tr -dc 'a-f0-9' </dev/urandom | head -c 48)" >> .env
fi
CREDS=$(grep '^ROSCRIBE_USERS=' .env | cut -d= -f2-)

# 2. (re)start the app locally
pkill -f "app/workspace.py" 2>/dev/null || true
sleep 1
.venv/bin/python app/workspace.py > /tmp/workspace_full.log 2>&1 &
disown
printf "starting app"
for _ in $(seq 1 90); do curl -s -o /dev/null http://127.0.0.1:8080/ && break; printf "."; sleep 1; done
echo " up."

# 3. open the public Cloudflare tunnel
pkill -f "cloudflared tunnel" 2>/dev/null || true
cloudflared tunnel --url http://127.0.0.1:8080 > /tmp/cloudflared.log 2>&1 &
disown
URL=""
for _ in $(seq 1 40); do
  URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/cloudflared.log | head -1)
  [ -n "$URL" ] && break
  sleep 1
done

cat <<EOF

================  ROScribe is LIVE  ================
  URL    : ${URL:-<not ready — check /tmp/cloudflared.log>}
  Login  : ${CREDS}
  Share the URL + login with your closed group.
  This Mac is the server — keep this terminal open.
  Stop:  pkill -f 'cloudflared tunnel'; pkill -f app/workspace.py
===================================================
EOF
