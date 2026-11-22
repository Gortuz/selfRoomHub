#!/bin/zsh
# Al dormir: suelta el parlante y apaga el Bluetooth para que la Mac dormida no lo acepte.
source "$HOME/.config/selfroomhub/macos.env" 2>/dev/null
BLUEUTIL=/opt/homebrew/bin/blueutil
[[ -n "$SPEAKER_BT_ADDRESS" ]] && $BLUEUTIL --disconnect "$SPEAKER_BT_ADDRESS" 2>/dev/null
$BLUEUTIL --power 0
