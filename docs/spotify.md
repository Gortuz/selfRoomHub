# Spotify

El backend controla la reproducción por la Web API de Spotify (PKCE, sin secreto de cliente) y reproduce en un dispositivo Spotify Connect concreto, por ejemplo la app de Spotify del propio teléfono servidor. Requiere Spotify Premium.

## 1. Crear la app

1. Entra en <https://developer.spotify.com/dashboard> y crea una app.
2. Nombre y descripción a tu gusto.
3. **Redirect URI**: `http://127.0.0.1:8000/spotify/callback`. Spotify exige loopback `127.0.0.1` (no `localhost`) o https.
4. Marca **Web API**.
5. Copia el **Client ID** (no hace falta el secreto).

## 2. Variables de entorno (`backend/.env`)

```
SELFROOMHUB_SPOTIFY_CLIENT_ID=<client id>
# SELFROOMHUB_SPOTIFY_REDIRECT_URI=http://127.0.0.1:8000/spotify/callback
# SELFROOMHUB_SPOTIFY_DEVICE=<nombre del dispositivo Connect>
# SELFROOMHUB_SPOTIFY_TOKEN_FILE=~/.local/state/selfroomhub/spotify.json
```

Los tokens se guardan en el archivo indicado con permisos 600. Sin client id, los endpoints responden 409.

## 3. Vincular

Abre en un navegador que llegue al backend como `127.0.0.1`:

```
http://127.0.0.1:8000/spotify/login?token=<SELFROOMHUB_TOKEN>
```

- En el propio servidor, el navegador del teléfono ya cumple esto.
- Desde otra máquina, redirige el puerto: `adb forward tcp:8799 tcp:8000`, pon como Redirect URI (en el dashboard y en `SELFROOMHUB_SPOTIFY_REDIRECT_URI`) `http://127.0.0.1:8799/spotify/callback` y abre `http://127.0.0.1:8799/spotify/login?token=...`.

Acepta los permisos; verás "Spotify vinculado". El refresh token se renueva solo.

## 4. Elegir el dispositivo

Con la app de Spotify abierta en el dispositivo:

```
curl -H "Authorization: Bearer $TOKEN" http://<servidor>:8000/spotify/status
```

Copia el `name` del dispositivo a `SELFROOMHUB_SPOTIFY_DEVICE` (la coincidencia ignora mayúsculas y acentos). Vacío: se usa el dispositivo activo o el primer Smartphone.

Reproducir:

```
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"query": "Soda Stereo", "type": "artist", "shuffle": true}' \
  http://<servidor>:8000/spotify/play
```

`type` puede ser `artist`, `album`, `playlist` o `track`; en lugar de `query` se puede pasar `uri`.

## 5. Escena de ejemplo

```yaml
scenes:
  musica:
    - power: { device: parlantes, on: true }
    - spotify: { play: "Soda Stereo", type: artist, shuffle: true }
```

Si el dispositivo no aparece (Spotify cerrado o dormido), la escena envía la orden `wake` al panel, espera 3 s y reintenta una vez. Campos opcionales del paso: `uri`, `device`.
