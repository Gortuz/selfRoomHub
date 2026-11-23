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
