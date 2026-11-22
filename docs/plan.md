# Plan de implementación

Orden de trabajo para llevar selfRoomHub de cero a funcionando. Las fases 0 y 1 se desarrollan en una computadora; el servidor Android entra en la fase 2, cuando el backend ya funciona.

## Fase 0: credenciales y prueba manual

Objetivo: encender y apagar un enchufe Tuya desde un script, sin código del proyecto.

1. Crear cuenta en [Tuya IoT Platform](https://platform.tuya.com), crear un proyecto Cloud y vincular la cuenta de Smart Life escaneando el QR desde la app.
2. `pip install tinytuya` y `python -m tinytuya wizard` para obtener la clave local de cada dispositivo.
3. `python -m tinytuya scan` para obtener la IP local y la versión de protocolo (3.3, 3.4 o 3.5).
4. Script mínimo que encienda y apague el enchufe.
5. Reservar en el router la IP del enchufe por su MAC.

Resultado: ID, clave local, IP y versión de cada dispositivo, guardados fuera del repo.

## Fase 1: backend base

Objetivo: controlar los dispositivos por HTTP desde la computadora de desarrollo.

- Proyecto en `backend/` con FastAPI, `ruff` y `pytest`.
- Interfaz `Device` (`on`, `off`, `status`), adaptador `TuyaDevice` y doble `FakeDevice` para tests.
- Carga de dispositivos desde `config/devices.yaml`; plantilla `config/devices.example.yaml` en el repo.
- Endpoints `GET /health`, `GET /devices`, `POST /devices/{id}/power`.
- Autenticación con token Bearer leído de `.env`.

Resultado: `curl` contra la API enciende y apaga el enchufe real.

## Fase 2: servidor en Android

Objetivo: el backend corre solo, 24/7, en un Android con Termux.

- Termux desde F-Droid, Python, clonar el repo, crear `.env` y `config/devices.yaml`.
- Termux:Boot + `termux-wake-lock` para arranque automático y evitar el sueño.
- Desactivar la optimización de batería para Termux; reservar la IP del servidor en el router.
- Documentar todo en `docs/setup-termux.md`.

Resultado: el backend sobrevive a reinicios del teléfono.

## Fase 3: clientes

Objetivo: usar el sistema sin abrir una terminal.

- Atajos de iOS (Siri) que llaman a la API.
- Stickers NFC que disparan esos atajos (automatización de Atajos en iOS, o NFC Tools / Tasker en Android).
- Tailscale en servidor y clientes para acceso fuera de casa.

## Fase 4: escenas

- `POST /scenes/{name}` con escenas definidas en configuración (por ejemplo `apagar_todo`).

## Fase 5: pantalla

- App Kotlin + Jetpack Compose: reloj, estado de dispositivos, horizontal, siempre encendida, autoarranque.
- Endpoint `GET /dashboard` que agrega lo que la pantalla necesita.

## Fase 6: más dispositivos

- Probar un solo dispositivo de cada marca nueva antes de comprar más.
- Adaptadores `tapo` y `python-kasa` según demanda.

## Fase 7: integraciones

- Clima con Open-Meteo (zona horaria y ubicación por configuración).
- Spotify Web API con PKCE.
- Calendario.

## Fase 8: endurecer

- Watchdog que reinicia el proceso si cae.
- Límite de carga de batería en el servidor.
- Notificación cuando el backend o un dispositivo deja de responder.
