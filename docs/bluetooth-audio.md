# Audio Bluetooth compartido entre varios equipos

## El problema

Muchos parlantes Bluetooth recuerdan pocos dispositivos emparejados y, al encenderse, solo se conectan cuando el dispositivo inicia la conexión. Si hay varios equipos cerca (Mac, iPhone, servidor), el parlante termina en el que reconecte primero, y no hay forma fiable de pedirle a otro que lo suelte.

## La solución

El servidor Android es el reproductor principal: reproduce con Spotify Connect y es el que se conecta al parlante. Para pasar el audio a otro equipo (por ejemplo, la Mac para ver una película), uno suelta el parlante y el otro lo conecta. El backend expone esas órdenes por API:

- `GET /bluetooth`
- `POST /bluetooth/{id}/connect`
- `POST /bluetooth/{id}/disconnect`

## Por qué hace falta Shizuku

Conectar y desconectar un dispositivo Bluetooth clásico sin interfaz requiere el permiso `BLUETOOTH_PRIVILEGED`, que solo tiene el usuario `shell` de Android (no Termux, ni siquiera con root ausente). Shizuku permite ejecutar comandos como `shell` desde Termux mediante `rish`. La herramienta `tools/btctl` (`BtCtl`) hace el trabajo y el backend la invoca vía `rish`.

## Pasos

1. **Instalar Shizuku** desde sus releases de GitHub e iniciarlo.
2. Dar permiso a Shizuku para que pueda reiniciarse solo:
   ```bash
   adb shell pm grant moe.shizuku.privileged.api android.permission.WRITE_SECURE_SETTINGS
   ```
3. Vincular con **depuración inalámbrica** (Opciones de desarrollador) y activar **Start on boot** en Shizuku.
4. **Instalar rish en Termux**: del APK de Shizuku extrae `assets/rish` y `assets/rish_shizuku.dex`; en `rish` cambia `PKG` por `com.termux`; copia ambos a `~/.local/bin` y ejecuta `chmod 400 ~/.local/bin/rish_shizuku.dex`.
5. **Compilar btctl** en la máquina de desarrollo (requiere JDK 21 y Android SDK con `platforms/android-36` y `build-tools/36.0.0`):
   ```bash
   tools/btctl/build.sh        # genera tools/btctl/build/btctl.dex
   ```
6. **Instalar btctl** en el servidor (con el dex ya copiado al repo en Termux):
   ```bash
   bash scripts/termux/install-btctl.sh [ruta/al/btctl.dex]
   ```
   Variables opcionales: `RISH` (script de instalación) y, para el backend, `SELFROOMHUB_RISH` y `SELFROOMHUB_BTCTL_DEX` (por defecto `~/.local/bin/rish` y `/data/local/tmp/btctl.dex`).
7. **Configurar** la sección `bluetooth` de `config/devices.yaml`:
   ```yaml
   bluetooth:
     - id: parlantes
       name: Parlantes
       address: AA:BB:CC:DD:EE:FF
   ```

Prueba manual en Termux:

```bash
env -u LD_LIBRARY_PATH -u LD_PRELOAD ~/.local/bin/rish -c \
  "unset LD_LIBRARY_PATH LD_PRELOAD; CLASSPATH=/data/local/tmp/btctl.dex app_process / BtCtl status AA:BB:CC:DD:EE:FF"
```

Nota: `LD_LIBRARY_PATH` y `LD_PRELOAD` de Termux rompen `app_process`, por eso se limpian siempre.

## Atajos de ejemplo

En la Mac (con `blueutil`):

- **Movie mode**: `POST /bluetooth/<id>/disconnect` y luego `blueutil --connect <dirección>`.
- **Music mode**: `blueutil --disconnect <dirección>` y luego `POST /bluetooth/<id>/connect`.
