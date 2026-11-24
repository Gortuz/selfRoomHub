# Panel (cliente visual)

Panel web servido por el backend en `/panel/`. En el servidor Android lo muestra una app kiosco (`android/`); en cualquier otro equipo basta un navegador.

## Contrato de la API usada por el panel

Autenticación: el panel recibe el token en el fragmento de la URL (`/panel/#token=...`, nunca llega al servidor ni a los logs), lo guarda en `localStorage` y lo manda como `Authorization: Bearer`.

| Método | Ruta | Auth | Uso |
|---|---|---|---|
| GET | `/panel/` | no | HTML/JS/CSS estáticos |
| GET | `/health` | no | `{"status":"ok","bluetooth":"ok"\|"unavailable"}` |
| GET | `/devices` | sí | Estado de enchufes |
| POST | `/devices/{id}/toggle` | sí | Encender/apagar |
| GET | `/bluetooth` | sí | `[{"id","name","connected"}]` (¿el servidor tiene el parlante?) |
| POST | `/bluetooth/{id}/connect` | sí | Traer el audio al servidor |
| GET | `/now-playing` | sí | Ver abajo |
| PUT | `/now-playing` | sí | Lo publica la app kiosco |
| GET | `/now-playing/art` | no | Portada actual (JPEG/PNG); 404 si no hay |

### `GET /now-playing`

```json
{
  "playing": true,
  "title": "Canción", "artist": "Artista", "album": "Álbum",
  "app": "com.spotify.music",
  "art_url": "/now-playing/art?v=3f2a9c1e",
  "updated_at": "2026-11-22T20:15:03-05:00"
}
```

Sin nada sonando: `{"playing": false, "title": null, ..., "art_url": null, "updated_at": ...}`. `art_url` cambia de `v` cuando cambia la imagen (sirve para evitar caché).

### `PUT /now-playing`

```json
{
  "playing": true,
  "title": "Canción", "artist": "Artista", "album": "Álbum",
  "app": "com.spotify.music",
  "art_base64": "<jpeg o png en base64, opcional>"
}
```

`{"playing": false}` (resto omitido) deja el estado en "nada sonando" y borra la portada. Límite: imagen de hasta 2 MB decodificada.

## Controles de reproducción y volumen

El panel no habla con el reproductor: manda órdenes al backend y la app kiosco del servidor las ejecuta (así funciona desde cualquier navegador).

| Método | Ruta | Auth | Uso |
|---|---|---|---|
| POST | `/media/command` | sí | Encola una orden; responde `202 {"id": n}` |
| GET | `/media/commands?after=<id>&wait=<s>` | sí | Long-poll de la app kiosco: devuelve las órdenes con `id > after` (espera hasta `wait` segundos, máx. 30, si no hay) |

Cuerpo de `POST /media/command`:

```json
{"action": "toggle" | "play" | "pause" | "next" | "previous" | "volume", "value": 0-100}
```

`value` solo (y obligatorio) para `volume`, en porcentaje. Respuesta de `GET /media/commands`: `[{"id": 7, "action": "next", "value": null, "created_at": "..."}]`. Las órdenes de más de 10 s se descartan (no se ejecuta una orden vieja tras una reconexión). Los ids son crecientes; `after=0` en el primer arranque devuelve solo órdenes vigentes.

`GET`/`PUT /now-playing` agregan `"volume": 0-100 | null` (volumen de medios del servidor, en porcentaje). La app kiosco lo informa al cambiar el volumen, aunque no haya música.

## Posición de reproducción y letras

`PUT /now-playing` acepta además (todos opcionales, la app kiosco los informa):

```json
{"position_ms": 61234, "duration_ms": 215000, "position_at": 1795400000000, "speed": 1.0}
```

`position_at` es la hora (epoch en ms, reloj del servidor/teléfono) en que se midió `position_ms`. `GET /now-playing` devuelve `position_ms` ya **extrapolado al momento de la respuesta** (si `playing`, suma `(ahora - position_at) * speed`, sin pasar de `duration_ms`) y `duration_ms`; el panel sigue extrapolando con su propio reloj desde que recibe la respuesta. Sin datos: `null`.

| Método | Ruta | Auth | Uso |
|---|---|---|---|
| GET | `/lyrics` | sí | Letra de lo que suena ahora, desde [LRCLIB](https://lrclib.net) |

Respuesta:

```json
{
  "title": "Octopus's Garden", "artist": "The Beatles",
  "synced": [{"t": 12340, "line": "I'd like to be under the sea"}],
  "plain": "I'd like to be under the sea\n...",
  "instrumental": false,
  "source": "lrclib"
}
```

`synced` es `null` si LRCLIB solo tiene letra sin tiempos. `404 {"detail": "Sin letra para esta canción"}` si no hay nada o no suena nada; `503` si LRCLIB no responde. El backend cachea por canción.

## Escenas

Una escena es una lista de pasos definida en `config/devices.yaml`; un atajo, un sticker NFC o el panel la disparan con una sola petición.

```yaml
scenes:
  charly:
    - power: { device: parlantes, on: true }
    - wait: 4
    - bluetooth: { id: parlantes, connect: true }
    - media: { action: play_search, query: "Charly García", focus: artist }
```

Pasos: `power {device, on}`, `toggle {device}`, `bluetooth {id, connect}`, `media {action, value?, query?, focus?}` (encola una orden como `POST /media/command`), `wake` (enciende la pantalla del servidor), `wait <segundos>` (máx. 30).

| Método | Ruta | Auth | Uso |
|---|---|---|---|
| GET | `/scenes` | sí | `[{"name": "charly", "steps": 4}]` |
| POST | `/scenes/{name}` | sí | Ejecuta los pasos en orden; `200 {"name", "ok", "steps": [{"step": "power", "ok": true, "detail": "..."}]}`; un paso que falla no detiene los siguientes (`ok: false` global); 404 si no existe |

## Órdenes nuevas para la app kiosco

`POST /media/command` acepta además:

- `{"action": "play_search", "query": "Charly García", "focus": "artist" | "album" | "playlist" | "any"}`: la app pide al reproductor que busque y reproduzca (Spotify vía `playFromSearch`).
- `{"action": "wake"}`: la app enciende la pantalla y trae el panel al frente.

## Pantalla y brillo (solo dentro de la app kiosco)

La app expone a la página `window.Android`:

- `setKeepAwake(boolean)`: mantener o soltar la pantalla encendida.
- `screenOffTimeout()`: tiempo de apagado del sistema en ms.
- `setBrightness(number 0–1)` / `getBrightness()`: brillo de la ventana del panel (se recuerda entre arranques; -1 = el del sistema).

Además la app enciende la pantalla sola cuando empieza a sonar música.

## Temporizador, modo día/noche y rutinas

| Método | Ruta | Auth | Uso |
|---|---|---|---|
| POST | `/devices/{id}/timer` | sí | `{"minutes": 45}` apaga el dispositivo tras ese tiempo (cuenta el propio enchufe); `{"minutes": 0}` cancela. 501 si el dispositivo no tiene temporizador |
| GET | `/mode` | sí | `{"mode": "day"\|"night", "source": "scene"\|"schedule"}` |
| PUT | `/mode` | sí | `{"mode": "day"\|"night"\|"auto"}`; un modo forzado dura hasta el próximo cambio del horario (`SELFROOMHUB_NIGHT_FROM`/`_TO`, por defecto 23:00 y 06:00); `auto` vuelve al horario |
| POST | `/routines/{name}` | sí | Ejecuta la escena cuya ventana horaria contiene la hora actual; 409 si ninguna aplica |

Apagado suave: un dispositivo con `audio: true` en `devices.yaml` (los parlantes) se apaga pausando antes la música y esperando 1,5 s para evitar el "pop"; `POST /devices/{id}/power?hard=true` corta sin pausa.
Con temporizador de 2 min o más en un dispositivo de audio, el volumen baja en escalones durante ~45 s antes del final (empieza 60 s antes), se pausa y se restaura el volumen original; reprogramar, poner `minutes: 0` o apagar lo cancela.

Pasos de escena nuevos: `timer: { device, minutes }` y `mode: night | day | auto`.

```yaml
routines:
  cama:
    - { from: "22:00", to: "06:30", scene: noche }   # cruza la medianoche
    - { from: "06:30", to: "22:00", scene: dia }
```

El panel consulta `/mode` y, en modo noche, se atenúa, muestra el reloj y no retiene la pantalla aunque haya música.
