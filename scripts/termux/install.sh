#!/data/data/com.termux/files/usr/bin/bash
# Instala selfRoomHub en Termux. Ejecutar desde la raíz del repo clonado.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="$REPO_DIR/backend/.venv"

pkg update -y
# cryptography desde pkg: compilarla con pip en Android suele fallar
pkg install -y python python-cryptography git openssh termux-api

# --system-site-packages para que el venv vea python-cryptography de pkg
python -m venv --system-site-packages "$VENV"
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install -e "$REPO_DIR/backend"

# Arranque automático con Termux:Boot
mkdir -p "$HOME/.termux/boot"
ln -sf "$REPO_DIR/scripts/termux/boot.sh" "$HOME/.termux/boot/selfroomhub"
chmod +x "$REPO_DIR/scripts/termux/"*.sh

echo
echo "Instalado. Falta crear backend/.env y config/devices.yaml (ver docs/setup-termux.md)."
