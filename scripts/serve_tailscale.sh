#!/usr/bin/env bash
# Put ROScribe online at a STABLE, branded URL via Tailscale Funnel:
#   https://roscribesl.<your-tailnet>.ts.net
# Prereqs (one-time, see the runbook): install Tailscale, `tailscale up
# --hostname=roscribesl`, and enable HTTPS + Funnel in the admin console.
# Everything (index, PDFs, breakdown LLM) stays on THIS machine.
#
#   ./scripts/serve_tailscale.sh
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:/Applications/Tailscale.app/Contents/MacOS:$PATH"

# 1. login + session secret (persisted in .env)
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
printf "app:"; for _ in $(seq 1 90); do curl -s -o /dev/null http://127.0.0.1:8080/ && { echo " up"; break; }; printf "."; sleep 1; done

# 3. expose it publicly via Tailscale Funnel (stable URL)
if ! command -v tailscale >/dev/null 2>&1; then
  echo "ERROR: 'tailscale' not found. Install it and complete the runbook first."; exit 1
fi
tailscale set --hostname=roscribesl 2>/dev/null || true   # -> roscribesl.<tailnet>.ts.net
tailscale funnel reset 2>/dev/null || true                # clear stale public ingress (fixes mobile ERR_SSL_PROTOCOL_ERROR)
tailscale funnel --bg 8080 || {
  echo "Funnel failed. Check: logged in (tailscale status), Funnel + HTTPS enabled in the admin console."
  echo "If it printed a link to enable Funnel, open it, allow Funnel, then re-run this script."
  exit 1
}

echo ""
echo "============== ROScribe is LIVE (stable Tailscale URL) =============="
tailscale funnel status 2>/dev/null | grep -iE 'https://' || echo "  (run: tailscale funnel status  to see the URL)"
echo "  Login : ${CREDS}"
echo "  Stable across restarts. Keep this Mac on. Stop:  tailscale funnel reset"
echo "===================================================================="
