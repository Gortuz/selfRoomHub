#!/bin/zsh
# Instala el agente de la Mac: apaga el Bluetooth al dormir y lo prende al despertar la pantalla.
# Uso: zsh clients/macos/install.sh <dirección-bluetooth-del-parlante>
set -euo pipefail

ADDR="${1:-}"
if [[ -z "$ADDR" ]]; then
  echo "Uso: $0 <dirección-bluetooth>   (búscala con: blueutil --paired)" >&2
  exit 1
fi

DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="dev.selfroomhub.sleepwatcher"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
SW="$(brew --prefix)/opt/sleepwatcher/sbin/sleepwatcher"

brew list blueutil >/dev/null 2>&1 || brew install blueutil
brew list sleepwatcher >/dev/null 2>&1 || brew install sleepwatcher

mkdir -p "$HOME/.config/selfroomhub"
echo "SPEAKER_BT_ADDRESS=$ADDR" > "$HOME/.config/selfroomhub/macos.env"
chmod +x "$DIR/sleep.sh" "$DIR/wake.sh"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$SW</string>
    <string>-s</string><string>$DIR/sleep.sh</string>
    <string>-W</string><string>$DIR/wake.sh</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Agente instalado: $LABEL"
