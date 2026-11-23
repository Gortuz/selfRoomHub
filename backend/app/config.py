"""Carga de .env y devices.yaml."""

import os
import re
from collections.abc import Collection
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from app.bluetooth import BluetoothTarget, normalize_address
from app.devices.base import Device
from app.devices.registry import build_device
from app.scenes import Step, parse_scenes

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
_VAR = re.compile(r"\$\{([^}]+)\}")


def load_env() -> None:
    load_dotenv(BACKEND_DIR / ".env")


def get_token() -> str:
    token = os.environ.get("SELFROOMHUB_TOKEN")
    if not token:
        raise RuntimeError("Falta la variable de entorno SELFROOMHUB_TOKEN")
    return token


def get_config_path() -> Path:
    custom = os.environ.get("SELFROOMHUB_CONFIG")
    return Path(custom) if custom else REPO_ROOT / "config" / "devices.yaml"


def _interpolate(value: Any) -> Any:
    if isinstance(value, str):

        def repl(m: re.Match[str]) -> str:
            name = m.group(1)
            if name not in os.environ:
                raise ValueError(f"Variable de entorno no definida: {name}")
            return os.environ[name]

        return _VAR.sub(repl, value)
    if isinstance(value, dict):
        return {k: _interpolate(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate(v) for v in value]
    return value


def load_devices(path: Path) -> dict[str, Device]:
    if not path.is_file():
        raise FileNotFoundError(f"No existe el archivo de configuración: {path}")
    data = yaml.safe_load(path.read_text()) or {}
    specs = _interpolate(data.get("devices") or [])
    devices: dict[str, Device] = {}
    for spec in specs:
        device = build_device(spec)
        if device.id in devices:
            raise ValueError(f"ID de dispositivo duplicado: {device.id}")
        devices[device.id] = device
    return devices


def load_bluetooth(path: Path) -> dict[str, BluetoothTarget]:
    """Sección opcional `bluetooth` de devices.yaml; vacía si no existe."""
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    specs = _interpolate(data.get("bluetooth") or [])
    targets: dict[str, BluetoothTarget] = {}
    for spec in specs:
        target = BluetoothTarget(
            id=spec["id"], name=spec["name"], address=normalize_address(spec["address"])
        )
        if target.id in targets:
            raise ValueError(f"ID de Bluetooth duplicado: {target.id}")
        targets[target.id] = target
    return targets


def load_scenes(
    path: Path, device_ids: Collection[str], bt_ids: Collection[str]
) -> dict[str, list[Step]]:
    """Sección opcional `scenes` de devices.yaml; vacía si no existe."""
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    return parse_scenes(_interpolate(data.get("scenes")), device_ids, bt_ids)
