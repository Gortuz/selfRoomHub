#!/data/data/com.termux/files/usr/bin/bash
# Lo ejecuta Termux:Boot al encender el teléfono (enlazado en ~/.termux/boot/).
termux-wake-lock
sshd
REPO_DIR="$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)"
# Evita duplicados si se ejecuta dos veces
pgrep -f "scripts/termux/run.sh" >/dev/null || nohup "$REPO_DIR/scripts/termux/run.sh" >/dev/null 2>&1 &
