# App kiosco del panel (Android)

App mínima (`android/`, package `dev.selfroomhub.panel`) que corre en el mismo Android que el backend:

- Muestra el panel (`<base_url>/panel/`) en un WebView a pantalla completa, horizontal, siempre encendida y en modo inmersivo.
- Si el backend aún no responde (por ejemplo tras reiniciar), muestra "Esperando al servidor…" y reintenta cada 5 s.
- Puede ser la app de inicio (HOME), de modo que arranca sola tras reiniciar.
- Un `NotificationListenerService` publica lo que suena en el teléfono (`PUT /now-playing`, ver [panel.md](panel.md)).

## Compilar

Requisitos: JDK 21 y Android SDK (platform 36). Crea `android/local.properties` (ignorado por Git) con `sdk.dir=/ruta/al/sdk`.

```sh
cd android
export JAVA_HOME=/ruta/al/jdk-21
./gradlew assembleDebug
# APK: app/build/outputs/apk/debug/app-debug.apk
```

## Instalar

```sh
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

## Conceder acceso a notificaciones

Necesario para leer las sesiones de medios:

```sh
adb shell cmd notification allow_listener dev.selfroomhub.panel/dev.selfroomhub.panel.MediaListenerService
```

O manualmente: Ajustes > Notificaciones > Acceso a notificaciones > selfRoomHub Panel.

## Configurar el token

La configuración se pasa por intent y se guarda cifrada (`EncryptedSharedPreferences`). Desde Termux, en la raíz del repo:

```sh
am start -n dev.selfroomhub.panel/.MainActivity \
  --es token "$(grep ^SELFROOMHUB_TOKEN= backend/.env | cut -d= -f2-)"
```

Opcionalmente `--es base_url http://host:puerto` (por defecto `http://127.0.0.1:8000`). Se reutiliza en los arranques siguientes. Sin token, la app muestra el comando necesario.

Nota: el tráfico HTTP plano (cleartext) está permitido en general, porque el backend no usa TLS y Android no permite restringir por rango de red en `network_security_config`. Úsalo solo en localhost / LAN / Tailscale.

## Controles de reproducción y volumen

El servicio de medios consulta `GET /media/commands` (long-poll) y ejecuta las órdenes sobre la sesión de medios activa:

- `toggle`: pausa si suena, si no reanuda. `play`, `pause`, `next`, `previous`: actúan sobre la misma sesión que se publica en now-playing. Sin sesión activa, `play`/`toggle` envían la tecla multimedia PLAY para que la última app de música reanude.
- `volume`: fija el volumen de **medios del teléfono** (STREAM_MUSIC) en porcentaje, sin mostrar la barra del sistema.

El volumen actual se informa en `volume` en cada `PUT /now-playing` y, con un retraso de ~300 ms, al cambiar (también con botones físicos y sin música). Cada `PUT /now-playing` incluye además, si se conocen, `position_ms`, `position_at` (hora de pared de la medición), `speed` y `duration_ms` (ver [panel.md](panel.md#posición-de-reproducción-y-letras)); un salto dentro de la canción (seek) llega como cambio de estado y se publica con el mismo debounce de 500 ms. Requiere el mismo acceso a notificaciones que now-playing. Ante errores de red reintenta cada 3 s; con 401 (token mal configurado), cada 30 s.

## Arrancar tras reiniciar

Elige la app como pantalla de inicio: Ajustes > Apps > Apps predeterminadas > App de inicio > selfRoomHub Panel (o pulsa Inicio y elige "Siempre"). Al reiniciar, Android la abre sola. Termux:Boot arranca el backend; la app reintenta hasta que responda.

## Salir del kiosco

- Desde el panel: `window.Android.openSettings()` abre los Ajustes de Android (también existe `window.Android.appVersion()`).
- Con adb: `adb shell am start -a android.settings.SETTINGS`, o cambia la app de inicio y pulsa Inicio.
- El botón Atrás no cierra la app.

## Quitar restricciones de batería

Para que Android no mate la app ni el servicio de medios:

- Ajustes > Apps > selfRoomHub Panel > Batería > Sin restricciones.
- O por adb: `adb shell dumpsys deviceidle whitelist +dev.selfroomhub.panel`.
- Haz lo mismo con Termux, Termux:Boot y Termux:API.

> `base_url` solo acepta direcciones locales (`127.0.0.1`, `localhost`, `::1`): la actividad es pública y cualquier app del teléfono podría intentar mandar otro servidor para quedarse con el token.
