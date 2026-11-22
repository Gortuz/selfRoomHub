#!/data/data/com.termux/files/usr/bin/bash
# Copia btctl.dex a /data/local/tmp (legible por el usuario shell) usando rish.
# Uso: bash scripts/termux/install-btctl.sh [ruta/al/btctl.dex]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DEX="${1:-$REPO_ROOT/tools/btctl/build/btctl.dex}"
RISH="${RISH:-$HOME/.local/bin/rish}"

[ -f "$DEX" ] || { echo "No existe el dex: $DEX" >&2; exit 1; }
[ -x "$RISH" ] || { echo "No se encuentra rish: $RISH" >&2; exit 1; }

# Las variables de Termux rompen app_process / rish
env -u LD_LIBRARY_PATH -u LD_PRELOAD "$RISH" -c \
  'cat > /data/local/tmp/btctl.dex && chmod 644 /data/local/tmp/btctl.dex' < "$DEX"

echo "Instalado en /data/local/tmp/btctl.dex"
