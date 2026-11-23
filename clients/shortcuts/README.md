# Generador de atajos (iOS / macOS)

Crea y firma los atajos de selfRoomHub desde una Mac. Se importan con doble clic y se sincronizan por iCloud con el iPhone.

```bash
export SELFROOMHUB_TOKEN=...     # el de backend/.env
python3 clients/shortcuts/generate.py \
  --url http://<ip-del-servidor>:8000 --device <id-del-enchufe> \
  --bt-id <id-bluetooth> --bt-address AA:BB:CC:DD:EE:FF \
  --out /tmp/atajos
open /tmp/atajos/*.shortcut      # importar (de a uno si no aparecen los diálogos)
rm -rf /tmp/atajos               # contienen el token
```

| Atajo | Qué hace |
|---|---|
| Speakers on / off | Enciende o apaga el enchufe |
| Speakers | Alterna el enchufe (útil para un sticker NFC) |
| Movie mode | Solo Mac: enciende, el servidor suelta el parlante Bluetooth y la Mac se conecta (`blueutil`) |
| Music mode | Si corre en la Mac la suelta; luego el servidor se conecta al parlante |
| (escenas) | Con `--scene charly=Peluche`, un atajo "Peluche" que llama a `POST /scenes/charly`; ideal para un sticker NFC |

`--bt-id` y `--bt-address` son opcionales: sin ellos solo se generan los tres primeros. Ver `docs/bluetooth-audio.md`.

Requisitos en la Mac: `brew install blueutil` y, en Atajos → Ajustes → Avanzado, "Permitir ejecutar scripts". Si ya existe un atajo con el mismo nombre, bórralo antes de importar (si no, se crea "Nombre 1").
