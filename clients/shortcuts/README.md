# Generador de atajos (iOS / macOS)

Crea y firma los atajos de selfRoomHub desde una Mac. Se importan con doble clic y se sincronizan por iCloud con el iPhone.

```bash
export SELFROOMHUB_TOKEN=...     # el de backend/.env
python3 clients/shortcuts/generate.py \
  --url http://<ip-del-servidor>:8000 --device <id-del-enchufe> \
  --bt-id <id-bluetooth> --bt-address AA:BB:CC:DD:EE:FF \
  --light <id-del-foco> --movie-scene pelicula \
  --scene noche="Buenas noches" --scene dia="Buenos días" --scene apagar_todo="Me voy" \
  --menu Noche=noche --menu Día=dia --menu Película=pelicula --menu "Apagar todo=apagar_todo" \
  --out /tmp/atajos
open /tmp/atajos/*.shortcut      # importar (de a uno si no aparecen los diálogos)
rm -rf /tmp/atajos               # contienen el token
```

| Atajo | Qué hace |
|---|---|
| Prende los parlantes / Apaga los parlantes | Enciende o apaga el enchufe |
| Parlantes | Alterna el enchufe (útil para un sticker NFC) |
| Modo película | En la Mac: corre `--movie-scene` (o enciende y suelta el parlante) y la Mac se conecta (`blueutil`). En otro equipo corre la escena y avisa |
| Modo música | Si corre en la Mac la suelta; luego el servidor se conecta al parlante |
| Foco | Con `--light`: alterna el foco |
| Foco cálido / Foco blanco / Foco de noche | 70 % 2700 K / 100 % 5000 K / 10 % 2500 K |
| Brillo del foco | Pregunta un número (1–100) y lo aplica; por voz se responde diciendo el número |
| Cuarto | Con `--menu`: menú de escenas; Siri lee las opciones y se elige con la voz |
| (escenas) | Con `--scene charly=Peluche`, un atajo "Peluche" que llama a `POST /scenes/charly`; ideal para un sticker NFC |
| (rutinas) | Con `--routine cama=Cama`, un atajo que llama a `POST /routines/cama`: la escena depende de la hora |

`--bt-id` y `--bt-address` son opcionales: sin ellos solo se generan los tres primeros. Ver `docs/bluetooth-audio.md`.

Requisitos en la Mac: `brew install blueutil` y, en Atajos → Ajustes → Avanzado, "Permitir ejecutar scripts". Si ya existe un atajo con el mismo nombre, bórralo antes de importar (si no, se crea "Nombre 1").

Nombres pensados para Siri en español. Evita "prende/apaga la luz": Siri las toma como órdenes de la app Casa y no corre el atajo.
