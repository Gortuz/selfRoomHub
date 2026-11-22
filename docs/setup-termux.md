# Servidor en Android con Termux

Cómo convertir un Android viejo en el servidor de selfRoomHub. Probado en un Redmi Note 8 con LineageOS (Android 16). Sin root.

> Si usas una Raspberry Pi, una laptop vieja o cualquier Linux, no necesitas esta guía: instala con `uv sync` o `pip install -e backend` y listo. Lo especial de Android es que `pydantic-core` (dependencia de FastAPI) no tiene versión precompilada y hay que compilarlo en el teléfono.

## 1. Apps

Instala desde el **mismo origen** las tres apps: GitHub releases o F-Droid. Las firmas de ambos orígenes son distintas y los plugins no funcionan si se mezclan. No uses Play Store (versión abandonada).

- [Termux](https://github.com/termux/termux-app/releases) (APK `arm64-v8a` para la mayoría de teléfonos)
- [Termux:Boot](https://github.com/termux/termux-boot/releases): ábrela una vez después de instalarla para activar el arranque automático.
- [Termux:API](https://github.com/termux/termux-api/releases)

Con ADB desde una computadora: `adb install <archivo>.apk`.

Android 15+ puede mostrar un aviso de "16 KB page size" al abrir Termux. Es solo un aviso en teléfonos con páginas de 4 KB.

## 2. Ajustes del teléfono

- **Batería**: Termux y Termux:Boot en "Sin restricciones". Con ADB:
  ```bash
  adb shell dumpsys deviceidle whitelist +com.termux
  adb shell dumpsys deviceidle whitelist +com.termux.boot
  ```
- **Wi-Fi**: en la red de casa, Privacidad → **Usar MAC del dispositivo**, y reserva su IP en el router (DHCP estático). Así los clientes siempre lo encuentran.

## 3. SSH (recomendado)

Para administrar el teléfono desde tu computadora. En Termux:

```bash
pkg update && pkg install openssh
mkdir -p ~/.ssh && echo "<tu llave pública>" >> ~/.ssh/authorized_keys
echo "PasswordAuthentication no" >> $PREFIX/etc/ssh/sshd_config
sshd
```

Desde la computadora: `ssh -p 8022 <ip-del-teléfono>`. El usuario lo da `whoami` en Termux (algo como `u0_a153`).

## 4. Instalar el backend

```bash
git clone https://github.com/Gortuz/selfRoomHub.git ~/selfRoomHub
cd ~/selfRoomHub
bash scripts/termux/install.sh
```

El script instala Python, `cryptography` (de los paquetes de Termux), Rust y compila las dependencias. **La primera vez tarda bastante** por la compilación de `pydantic-core`. Deja el teléfono cargando y con `termux-wake-lock` activo.

Si Termux actualiza Python a una versión nueva, el entorno virtual deja de funcionar: borra `backend/.venv` y vuelve a ejecutar el script.

## 5. Configuración

Copia desde tu computadora (no están en Git):

```bash
scp -P 8022 backend/.env <ip>:~/selfRoomHub/backend/.env
scp -P 8022 config/devices.yaml <ip>:~/selfRoomHub/config/devices.yaml
```

## 6. Arranque y supervisión

- `scripts/termux/run.sh`: corre el backend en el puerto 8000 y lo reinicia si se cae.
- `scripts/termux/boot.sh`: lo ejecuta Termux:Boot al encender el teléfono (`install.sh` lo enlaza en `~/.termux/boot/`). Activa el wake-lock, levanta `sshd` y arranca `run.sh`.

Para arrancar sin reiniciar el teléfono: `~/.termux/boot/selfroomhub`.

Logs en `~/.local/state/selfroomhub/`.

## 7. Probar

Desde otra máquina de la red:

```bash
curl http://<ip>:8000/health
curl -H "Authorization: Bearer <token>" http://<ip>:8000/devices
```
