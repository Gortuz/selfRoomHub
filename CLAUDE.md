# selfRoomHub

Domótica casera para un cuarto, de bajo presupuesto y sin hub comercial. Un celular Android viejo (o cualquier máquina Linux) corre el backend y controla los dispositivos Wi-Fi por red local. Pensado para que cualquiera lo replique con su propio hardware.

> El hardware y las decisiones de cada instalación concreta van en `CLAUDE.local.md` (no se commitea). Este archivo describe solo el proyecto genérico.

## Objetivo

- Encender, apagar y consultar enchufes y focos inteligentes Wi-Fi desde código, en red local.
- Sin depender de Alexa, Google Home, Apple Home ni de un hub dedicado.
- Escenas que agrupan acciones (por ejemplo `apagar_todo`).
- Clientes simples: atajos de iOS (Siri), Tasker / NFC Tools en Android, stickers NFC y una pantalla de información.
- Integraciones opcionales: Spotify, clima, calendario.
- Acceso remoto sin abrir puertos (Tailscale).

## Hardware soportado

| Rol | Requisito |
|---|---|
| Servidor | Android con Termux (sin root) o cualquier Linux con Python 3.11+ |
| Pantalla (opcional) | Android con la app Kotlin del proyecto; puede ser el mismo servidor |
| Clientes | iPhone (Atajos), Android (Tasker / NFC Tools), navegador, `curl` |
| Dispositivos | Enchufes y focos Wi-Fi con control local por librería Python (ver adaptadores) |

### Adaptadores de dispositivos

| Marca / ecosistema | Librería | Estado |
|---|---|---|
| Tuya / Smart Life | `tinytuya` | Primero en implementarse. Requiere ID y clave local de cada dispositivo. |
| TP-Link Tapo | `tapo` | Pendiente. Verificar compatibilidad del modelo antes de usarlo. |
| TP-Link Kasa | `python-kasa` | Pendiente. |

Agregar una marca nueva = escribir un adaptador que implemente la interfaz `Device`.

## Decisiones de diseño

1. **Backend en Python + FastAPI**, pensado para correr en Termux. Root no es requisito.
2. **Control local**: se habla directo con los dispositivos en la LAN; la nube del fabricante solo se usa, si acaso, para obtener credenciales locales una vez.
3. **Matter fuera de alcance** mientras no haya un controlador dedicado: el emparejamiento por Bluetooth no es viable desde Termux.
4. **Dispositivos y escenas definidos por configuración**, no en código. Cada instalación tiene su `config/devices.yaml` (ignorado por Git) a partir de `config/devices.example.yaml`.
5. **Pantalla**: app Kotlin + Jetpack Compose, horizontal, siempre encendida, autoarranque con `BOOT_COMPLETED`. Solo consume la API.
6. **Voz y NFC**: atajos de iOS o tareas de Android que hacen peticiones HTTP al backend. Sin apps propias en iOS.
7. **Spotify**: Web API con PKCE, refresh token guardado en el backend. Opcional.
8. **Clima**: Open-Meteo (sin clave). Ubicación por configuración.
9. **Acceso remoto**: Tailscale. Ningún puerto expuesto a internet.

## Arquitectura

```
Pantalla (Android) ──┐
Atajos / Siri (iOS) ──┼──> Backend Python (Termux / Linux)
NFC / Tasker        ──┘        │
                               ├──> adaptadores: tinytuya, tapo, python-kasa
                               ├──> Spotify Web API (opcional)
                               └──> Open-Meteo, calendario (opcional)
```

### Principios

- Una interfaz `Device` con `on()`, `off()`, `status()`. Un adaptador por marca.
- El backend es la única fuente de verdad del estado. Los clientes solo consultan y mandan órdenes.
- Sin lógica de negocio en la app Kotlin ni en los atajos.
- Nada específico de una instalación en el código: nombres, IPs, modelos y escenas viven en la configuración.
- Secretos (claves locales, tokens, contraseñas) en `.env` o archivos ignorados, nunca en Git.

## Endpoints

- `GET /health` (incluye `bluetooth: ok|unavailable` si hay Bluetooth configurado; `unavailable` = Shizuku inactivo)
- `GET /devices`
- `POST /devices/{id}/power` con body `{"on": true|false}`
- `POST /devices/{id}/toggle` (invierte el estado; útil para un solo sticker NFC o atajo)
- `POST /scenes/{name}`
- `GET /bluetooth`: lista los dispositivos Bluetooth configurados y si el servidor está conectado a cada uno
- `POST /bluetooth/{id}/connect`: conecta el servidor a ese dispositivo Bluetooth
- `POST /bluetooth/{id}/disconnect`: desconecta el servidor de ese dispositivo Bluetooth
- `GET /now-playing`, `POST /spotify/{accion}`
- `GET /weather`
- `GET /dashboard` (agregado para la pantalla)

Autenticación: token estático en `Authorization: Bearer ...`. En Android se guarda en `EncryptedSharedPreferences`.

## Estructura del repositorio

```
selfRoomHub/
├── CLAUDE.md
├── CLAUDE.local.md            # contexto de tu instalación (ignorado)
├── backend/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py            # FastAPI
│   │   ├── devices/
│   │   │   ├── base.py        # interfaz Device
│   │   │   ├── tuya.py
│   │   │   ├── tapo.py
│   │   │   └── kasa.py
│   │   ├── integrations/
│   │   │   ├── spotify.py
│   │   │   └── weather.py
│   │   └── config.py
│   └── tests/
├── config/
│   └── devices.example.yaml   # plantilla; copiar a devices.yaml
├── android/                   # app Kotlin + Compose
├── docs/
│   ├── setup-termux.md
│   └── tuya-local-key.md      # cómo obtener ID y clave local
└── scripts/
```

## Convenciones

- Python 3.11+, tipado con `typing`, formato y lint con `ruff`.
- Tests con `pytest`; los dispositivos reales se simulan con dobles.
- Commits consistentes en un solo idioma dentro del repo.
- Ramas por fase: `fase-1-tuya`, `fase-2-api`, etc.
- No commitear `.env`, `config/devices.yaml`, `CLAUDE.local.md` ni tokens.

## Fases

1. **Dispositivo base**: Termux + `tinytuya`. Script que enciende y apaga un enchufe Tuya. Termux:Boot para arranque automático.
2. **API**: FastAPI con dispositivos y escenas cargados desde configuración. Tests unitarios.
3. **Clientes**: atajos de iOS, tareas de Android y stickers NFC. Validar en LAN y por Tailscale.
4. **Pantalla**: app Kotlin con reloj, estado de dispositivos y música.
5. **Más adaptadores**: Tapo, Kasa u otros según demanda.
6. **Integraciones**: Spotify, clima, calendario.
7. **Endurecer**: límite de carga de batería, watchdog del proceso, notificaciones de caída.
8. **Documentar la replicación**: guía de instalación de cero a funcionando.

## Riesgos conocidos

- **Sueño del servidor Android**: si se duerme o pierde Wi-Fi, todo se detiene. Mitigar con wake-lock, reserva DHCP, optimización de batería desactivada y supervisor de procesos.
- **Claves locales de Tuya**: cambian si el dispositivo se restablece.
- **Compatibilidad de librerías**: no todos los modelos de una marca funcionan con su librería; verificar antes de comprar.
- **Actualizaciones de Android / ROM**: pueden romper Termux o el Wi-Fi. Probar después de cada actualización.

## Lo que Claude debe hacer en este proyecto

- Leer `CLAUDE.local.md` si existe para conocer la instalación concreta, pero no meter esos detalles en el código ni en la documentación genérica.
- Preguntar antes de asumir la marca o el modelo de un dispositivo.
- Verificar compatibilidad de librerías en su repositorio oficial antes de proponer una integración.
- No recomendar comprar hub ni dispositivos Matter sin revisar el presupuesto y las decisiones vigentes.
- Mantener el backend independiente de la app Kotlin y de los atajos.
- Escribir tests antes de tocar lógica de dispositivos.
