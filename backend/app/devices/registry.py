"""Mapa de tipo de dispositivo a su constructor."""

from typing import Any

from app.devices.base import Device
from app.devices.fake import FakeDevice
from app.devices.tuya import TuyaDevice

DEVICE_TYPES: dict[str, type[Device]] = {"tuya": TuyaDevice, "fake": FakeDevice}


def build_device(spec: dict[str, Any]) -> Device:
    spec = dict(spec)
    dtype = spec.pop("type", None)
    audio = spec.pop("audio", False)
    if not isinstance(audio, bool):
        raise ValueError(f"audio debe ser true/false (dispositivo {spec.get('id', '?')!r})")
    if dtype not in DEVICE_TYPES:
        raise ValueError(
            f"Tipo de dispositivo desconocido: {dtype!r} (válidos: {', '.join(DEVICE_TYPES)})"
        )
    try:
        device = DEVICE_TYPES[dtype](**spec)
    except TypeError as e:
        raise ValueError(
            f"Configuración inválida para dispositivo {spec.get('id', '?')!r} ({dtype}): {e}"
        ) from e
    device.audio = audio
    return device
