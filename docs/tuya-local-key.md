# Obtener la clave local de un dispositivo Tuya

Los dispositivos Tuya / Smart Life se controlan en red local con `tinytuya`, pero cada uno necesita su **clave local** (`local_key`). La app no la muestra: se pide una sola vez a la nube de Tuya. Después, el control es 100 % local.

Necesitas: el dispositivo ya emparejado en la app Smart Life (o Tuya Smart), una computadora en la misma red Wi-Fi y [`uv`](https://docs.astral.sh/uv/) o Python 3.11+.

## 1. Encontrar el dispositivo en la red

```bash
uv run --python 3.12 --with tinytuya python -m tinytuya scan
```

Anota de cada dispositivo: **Address** (IP local), **Device ID** y **Version** (3.3, 3.4 o 3.5). La IP que muestra la app suele ser la IP pública, no sirve.

Reserva esa IP en tu router (DHCP estático por MAC) para que no cambie.

## 2. Crear un proyecto en Tuya IoT Platform

1. Crea una cuenta en <https://platform.tuya.com>.
2. **Cloud → Development → Create Cloud Project**.
   - Development Method: **Smart Home**.
   - Data Center: el mismo de tu cuenta de la app. Para América suele ser **Western America**. Si eliges otro, los dispositivos no aparecen.
3. En la pantalla de servicios, acepta los que vienen por defecto (deben incluir **IoT Core** y **Authorization Token Management**).
4. En la pestaña **Overview** del proyecto copia **Access ID/Client ID** y **Access Secret/Client Secret**.

## 3. Vincular la cuenta de la app

1. En el proyecto: **Devices → Link App Account → Add App Account**. Aparece un QR.
2. En la app Smart Life: **Yo / Me → ícono de escanear** (arriba a la derecha) y escanea el QR. Confirma.
3. Tus dispositivos deberían aparecer en la pestaña **All Devices** del proyecto.

## 4. Ejecutar el asistente

En una carpeta de trabajo fuera del repo:

```bash
uv run --python 3.12 --with tinytuya python -m tinytuya wizard
```

Te pide el Access ID, el Access Secret, un Device ID cualquiera de los tuyos y la región (`us` para Western America). Al final genera `devices.json` con el `key` de cada dispositivo. Acepta cuando pregunte si quieres consultar el estado de los dispositivos: así confirmas que la clave funciona.

**`devices.json`, `tinytuya.json` y `snapshot.json` contienen secretos.** No los copies al repo.

## 5. Llevar los datos a selfRoomHub

- `backend/.env`: el Device ID y la clave local (ver `backend/.env.example`).
- `config/devices.yaml`: IP, versión y nombre del dispositivo, referenciando las variables de `.env` con `${VAR}` (ver `config/devices.example.yaml`).

## Notas

- La suscripción gratuita de Tuya IoT Core caduca cada cierto tiempo. Solo afecta al asistente; el control local sigue funcionando. Si necesitas volver a correr el asistente, renuévala desde el proyecto.
- Si restableces o vuelves a emparejar el dispositivo, **la clave local cambia**: repite el paso 4.
