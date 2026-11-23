"""Control Bluetooth del servidor (Android) vía rish + BtCtl.

BtCtl debe correr como el usuario shell de Android; desde Termux se logra con rish (Shizuku).
Ver docs/bluetooth-audio.md.
"""

import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ADDRESS_RE = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")
TIMEOUT_S = 15
DEFAULT_DEX = "/data/local/tmp/btctl.dex"


class BluetoothError(Exception):
    """Fallo al controlar el Bluetooth del servidor."""


@dataclass(frozen=True)
class BluetoothTarget:
    id: str
    name: str
    address: str


def normalize_address(address: str) -> str:
    """Devuelve la dirección en mayúsculas o lanza ValueError si no es válida."""
    addr = address.strip().upper()
    if not ADDRESS_RE.match(addr):
        raise ValueError(f"Dirección Bluetooth inválida: {address!r}")
    return addr


class BluetoothController:
    def __init__(
        self,
        runner: Callable[..., Any] = subprocess.run,
        rish: str | None = None,
        dex: str | None = None,
    ) -> None:
        self._run = runner
        self._rish = (
            rish
            or os.environ.get("SELFROOMHUB_RISH")
            or str(Path("~/.local/bin/rish").expanduser())
        )
        self._dex = dex or os.environ.get("SELFROOMHUB_BTCTL_DEX") or DEFAULT_DEX

    def _exec(self, action: str, address: str) -> list[str]:
        try:
            addr = normalize_address(address)
        except ValueError as e:
            raise BluetoothError(str(e)) from e
        # La dirección ya está validada: es segura dentro de la cadena de rish -c
        inner = (
            "unset LD_LIBRARY_PATH LD_PRELOAD; "
            f"CLASSPATH={self._dex} app_process / BtCtl {action} {addr}"
        )
        cmd = ["env", "-u", "LD_LIBRARY_PATH", "-u", "LD_PRELOAD", self._rish, "-c", inner]
        try:
            res = self._run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired as e:
            raise BluetoothError("Tiempo agotado al ejecutar btctl") from e
        except FileNotFoundError as e:
            raise BluetoothError(f"No se encuentra rish: {self._rish}") from e
        if res.returncode != 0:
            raise BluetoothError(f"btctl falló (código {res.returncode})")
        # Sin terminal, rish entrega la salida del comando por stderr
        output = ((res.stdout or "") + (res.stderr or "")).strip()
        parts = output.splitlines()[-1].split() if output else []
        if len(parts) != 2 or parts[0] != action:
            raise BluetoothError(f"Salida inesperada de btctl: {output!r}")
        return parts

    def _action(self, action: str, address: str) -> None:
        code = self._exec(action, address)[1]
        if code != "0":
            raise BluetoothError(f"{action} falló (código {code})")

    def available(self) -> bool:
        """True si rish responde (Shizuku activo). No lanza excepciones."""
        cmd = ["env", "-u", "LD_LIBRARY_PATH", "-u", "LD_PRELOAD", self._rish, "-c", "echo ok"]
        try:
            res = self._run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S)
        except (subprocess.TimeoutExpired, OSError):
            return False
        output = (res.stdout or "") + (res.stderr or "")
        return res.returncode == 0 and output.strip() == "ok"

    def connect(self, address: str) -> None:
        self._action("connect", address)

    def disconnect(self, address: str) -> None:
        self._action("disconnect", address)

    def is_connected(self, address: str) -> bool:
        value = self._exec("status", address)[1]
        if value not in ("true", "false"):
            raise BluetoothError(f"Estado inesperado de btctl: {value!r}")
        return value == "true"
