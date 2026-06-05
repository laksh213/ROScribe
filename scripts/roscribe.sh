#!/usr/bin/env bash
# ROScribe — the on/off switch.
#   ./scripts/roscribe.sh start     # start the app (:8080) + public Tailscale URL
#   ./scripts/roscribe.sh stop      # stop the app + take the public URL offline
#   ./scripts/roscribe.sh status    # what's running + the URL + login
#   ./scripts/roscribe.sh restart
#
# Everything (index, PDFs, breakdown LLM, your notes) stays on THIS machine.
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:/Applications/Tailscale.app/Contents/MacOS:$PATH"
APP="app/workspace.py"; PORT=8080; LOG=/tmp/roscribe_app.log

have_ts() { command -v tailscale >/dev/null 2>&1; }
app_up()  { curl -s -o /dev/null --max-time 2 "http://127.0.0.1:${PORT}/demo" 2>/dev/null; }

start() {
  # 1. login + session secret (persisted in .env)
  if ! grep -q '^ROSCRIBE_USERS=' .env 2>/dev/null; then
    PW=$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 10)
    echo "ROSCRIBE_USERS=laksh:${PW}" >> .env
    echo "ROSCRIBE_STORAGE_SECRET=$(LC_ALL=C tr -dc 'a-f0-9' </dev/urandom | head -c 48)" >> .env
  fi
  # 2. local app
  if app_up; then
    echo "app already running"
  else
    pkill -f "$APP" 2>/dev/null || true; sleep 1
    .venv/bin/python "$APP" > "$LOG" 2>&1 &
    disown
    printf "starting app"
    for _ in $(seq 1 90); do app_up && break; printf "."; sleep 1; done; echo " up"
  fi
  # 3. public URL via Tailscale Funnel (reset clears the stale ingress that caused mobile SSL errors)
  if have_ts; then
    tailscale set --hostname=roscribesl 2>/dev/null || true
    tailscale funnel reset 2>/dev/null || true
    tailscale funnel --bg "$PORT" 2>/dev/null || echo "  (Funnel not enabled — see scripts/serve_tailscale.sh runbook)"
  fi
  status
}

stop() {
  echo "stopping ROScribe…"
  pkill -f "$APP" 2>/dev/null && echo "  app stopped" || echo "  app not running"
  if have_ts; then tailscale funnel reset 2>/dev/null && echo "  public URL offline" || true; fi
}

status() {
  echo "──────────── ROScribe ────────────"
  if app_up; then echo "  app    : RUNNING  ·  http://localhost:${PORT}"; else echo "  app    : stopped"; fi
  if have_ts; then
    URL=$(tailscale funnel status 2>/dev/null | grep -oE 'https://[a-z0-9.-]+\.ts\.net' | head -1)
    if [ -n "${URL:-}" ]; then echo "  public : ${URL}  ·  demo: ${URL}/demo"; else echo "  public : offline"; fi
  fi
  CREDS=$(grep '^ROSCRIBE_USERS=' .env 2>/dev/null | cut -d= -f2-)
  [ -n "${CREDS:-}" ] && echo "  login  : ${CREDS}"
  echo "──────────────────────────────────"
}

case "${1:-start}" in
  start)   start ;;
  stop)    stop ;;
  restart) stop; sleep 1; start ;;
  status)  status ;;
  *) echo "usage: $0 {start|stop|status|restart}"; exit 1 ;;
esac
