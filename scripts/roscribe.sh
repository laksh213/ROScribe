#!/usr/bin/env bash
# ROScribe — the on/off switch.
#   ./scripts/roscribe.sh start     # start the app (:8080) + public Tailscale URL
#   ./scripts/roscribe.sh stop      # stop the app + take the public URL offline
#   ./scripts/roscribe.sh status    # what's running + the URL + login
#   ./scripts/roscribe.sh restart
#   ./scripts/roscribe.sh update [args]   # fetch + index new judgements, then restart
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
  if pgrep -f "$APP" >/dev/null 2>&1; then
    pkill -f "$APP" 2>/dev/null || true
    for _ in $(seq 1 10); do pgrep -f "$APP" >/dev/null 2>&1 || break; sleep 1; done
    pgrep -f "$APP" >/dev/null 2>&1 && pkill -9 -f "$APP" 2>/dev/null || true   # force-kill stragglers so restart always redeploys current code
    echo "  app stopped"
  else
    echo "  app not running"
  fi
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

update() {
  # Fetch + index new judgements, then redeploy so the app serves them.
  # Forward any extra args (e.g. --since 2026, --limit 20, --dry-run).
  echo "── ROScribe corpus update ──"
  if ! .venv/bin/python -m scripts.update_corpus "$@"; then
    echo "  update failed — app left as-is."; return 1
  fi
  # A dry/metadata-only run changes nothing servable; skip the restart for those.
  case " $* " in *" --dry-run "*|*" --metadata-only "*) echo "  (no restart needed)"; return 0 ;; esac
  echo "  restarting to serve the new judgements…"; restart
}

case "${1:-start}" in
  start)   start ;;
  stop)    stop ;;
  restart) stop; sleep 1; start ;;
  status)  status ;;
  update)  shift; update "$@" ;;
  *) echo "usage: $0 {start|stop|status|restart|update}"; exit 1 ;;
esac
