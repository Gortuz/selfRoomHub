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
