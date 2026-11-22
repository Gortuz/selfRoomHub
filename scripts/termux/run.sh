#!/data/data/com.termux/files/usr/bin/bash
# Mantiene el backend corriendo: si el proceso cae, lo reinicia.
REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
LOG_DIR="$HOME/.local/state/selfroomhub"
PORT="${SELFROOMHUB_PORT:-8000}"
mkdir -p "$LOG_DIR"

cd "$REPO_DIR/backend" || exit 1
while true; do
  echo "$(date -Iseconds) iniciando backend en :$PORT" >>"$LOG_DIR/run.log"
  .venv/bin/uvicorn app.main:create_app --factory --host 0.0.0.0 --port "$PORT" \
    >>"$LOG_DIR/backend.log" 2>&1
  echo "$(date -Iseconds) backend terminó (código $?), reinicio en 5 s" >>"$LOG_DIR/run.log"
  sleep 5
done
