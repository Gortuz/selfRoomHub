# Atajos de iOS, Siri y stickers NFC

Cada atajo es una sola petición HTTP al backend. Nada de lógica en el atajo: el backend decide.

Necesitas:
- La IP del servidor y el puerto (por ejemplo `http://192.168.1.20:8000`).
- El token (`SELFROOMHUB_TOKEN` en `backend/.env`). Guárdalo en tu gestor de contraseñas para tenerlo a mano en el iPhone.
- El `id` del dispositivo según `config/devices.yaml` (por ejemplo `parlantes`).

## Atajo base

1. App **Atajos → +**.
2. Agrega la acción **Obtener contenido de URL** (*Get Contents of URL*).
3. URL: `http://<ip>:8000/devices/<id>/toggle`
4. Toca la flecha para ver más opciones:
   - **Método**: `POST`
   - **Encabezados**: agrega `Authorization` con valor `Bearer <token>` (con el espacio después de `Bearer`).
5. Ponle de nombre la frase que dirás a Siri, por ejemplo **"Parlantes"**.

Prueba con ▶︎. La respuesta es el estado nuevo: `{"id": "parlantes", "online": true, "on": true, ...}`.

## Encender y apagar explícitos

Para frases como "Prende los parlantes" y "Apaga los parlantes", duplica el atajo base y cambia:

- URL: `http://<ip>:8000/devices/<id>/power`
- **Cuerpo de la solicitud**: `JSON`, con un campo `on` de tipo **Booleano** (`Verdadero` para encender, `Falso` para apagar).

Usar `power` en vez de `toggle` evita sorpresas: "prende" siempre prende, aunque ya estuviera prendido.

## Respuesta hablada (opcional)

Después de *Obtener contenido de URL*:

1. **Obtener valor del diccionario** → clave `on`.
2. **Si** el valor es `1` / verdadero → **Decir** "Encendidos"; de lo contrario → **Decir** "Apagados".

Si el servidor no responde, el atajo muestra el error de red; si el dispositivo está desconectado, el backend responde `503` con el motivo.

## Siri

El nombre del atajo es la frase: "Oye Siri, parlantes". No hace falta configurar nada más.

## Stickers NFC

Requiere iPhone XS o posterior.

1. **Atajos → Automatización → + → NFC**.
2. **Escanear** y acerca el sticker. Ponle un nombre.
3. Elige **Ejecutar inmediatamente** y desactiva **Notificar al ejecutarse** si no quieres el aviso.
4. Acción: **Ejecutar atajo** → el atajo base (`toggle`).

Un sticker con `toggle` sirve como interruptor: cada toque invierte el estado.

## Fuera de casa

Estas URLs solo funcionan en la red local. Para usarlas fuera, instala Tailscale en el servidor y en el iPhone y usa la IP de Tailscale del servidor (`100.x.y.z`) en lugar de la local.
