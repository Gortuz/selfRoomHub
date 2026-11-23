"""Batería del servidor Android vía Termux:API (`termux-battery-status`)."""

import json
import subprocess
import time
from collections.abc import Callable
from typing import Any

COMMAND = "termux-battery-status"
TIMEOUT_S = 15


class BatteryError(Exception):
    """No se pudo leer la batería (sin Termux:API o respuesta inválida)."""


class BatteryMonitor:
    def __init__(
        self,
        runner: Callable[..., Any] = subprocess.run,
        clock: Callable[[], float] = time.monotonic,
        ttl: float = 60,
    ) -> None:
        self._run = runner
        self._clock = clock
        self._ttl = ttl
        self._cached: dict[str, Any] | None = None
        self._at = float("-inf")

    def read(self) -> dict[str, Any]:
        # El comando tarda ~1 s: se reutiliza la última lectura un rato
        now = self._clock()
        if self._cached is not None and now - self._at < self._ttl:
            return self._cached
        try:
            res = self._run([COMMAND], capture_output=True, text=True, timeout=TIMEOUT_S)
        except (subprocess.TimeoutExpired, OSError) as e:
            raise BatteryError(f"No se pudo ejecutar {COMMAND}") from e
        if res.returncode != 0:
            raise BatteryError(f"{COMMAND} falló (código {res.returncode})")
        try:
            data = json.loads(res.stdout)
            status = str(data.get("status", "")).upper()
            battery = {
                "percentage": int(data["percentage"]),
                # Lleno y enchufado también cuenta como cargando
                "charging": status in ("CHARGING", "FULL"),
                "status": status,
                "temperature": data.get("temperature"),
            }
        except (ValueError, KeyError, TypeError) as e:
            raise BatteryError(f"Respuesta inesperada de {COMMAND}") from e
        self._cached, self._at = battery, now
        return battery
