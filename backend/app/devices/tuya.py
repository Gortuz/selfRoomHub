"""Adaptador Tuya / Smart Life con tinytuya."""

import threading
import time
from collections.abc import Callable
from typing import Any

import tinytuya

from app.devices.base import Device, DeviceError, DeviceStatus


class TuyaDevice(Device):
    def __init__(
        self,
        id: str,
        name: str,
        device_id: str,
        address: str,
        local_key: str,
        version: str | float = "3.5",
        switch_dp: int = 1,
        timer_dp: int = 9,
        client: Any = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.id = id
        self.name = name
        self.device_id = device_id
        self.address = address
        self.local_key = local_key
        self.version = float(version)
        self.switch_dp = switch_dp
        self.timer_dp = timer_dp
        self._client = client  # inyectable para tests
        self._clock = clock
        # El enchufe informa el valor programado pero no lo descuenta: se guarda cuándo termina
        self._timer_end: float | None = None
        # tinytuya no es seguro entre hilos y FastAPI atiende peticiones en paralelo
        self._lock = threading.Lock()

    @property
    def client(self) -> Any:
        # Creación perezosa: no abre nada hasta el primer uso
        if self._client is None:
            c = tinytuya.OutletDevice(
                dev_id=self.device_id,
                address=self.address,
                local_key=self.local_key,
                version=self.version,
            )
            c.set_socketTimeout(3)
            c.set_socketRetryLimit(2)
            self._client = c
        return self._client

    def _raise_on_error(self, result: Any) -> None:
        if isinstance(result, dict) and "Error" in result:
            raise DeviceError(f"{self.id}: {result['Error']}")

    def on(self) -> None:
        with self._lock:
            self._raise_on_error(self.client.turn_on(switch=self.switch_dp))

    def off(self) -> None:
        with self._lock:
            self._raise_on_error(self.client.turn_off(switch=self.switch_dp))

    def set_timer(self, seconds: int) -> None:
        # Cuenta regresiva en segundos en el dp del temporizador; 0 cancela
        try:
            with self._lock:
                result = self.client.set_value(self.timer_dp, seconds)
        except OSError as e:
            raise DeviceError(f"{self.id}: {e}") from e
        self._raise_on_error(result)
        self._timer_end = self._clock() + seconds if seconds > 0 else None

    def _timer_left(self, reported: Any) -> int | None:
        # 0 en el enchufe: no hay temporizador (se cumplió o lo cancelaron)
        if not isinstance(reported, int) or reported <= 0:
            self._timer_end = None
            return None
        if self._timer_end is None:  # programado desde otra app: cuenta desde ahora
            self._timer_end = self._clock() + reported
        return max(0, round(self._timer_end - self._clock()))

    def status(self) -> DeviceStatus:
        try:
            with self._lock:
                result = self.client.status()
            self._raise_on_error(result)
            value = result["dps"][str(self.switch_dp)]
            reported = result["dps"].get(str(self.timer_dp))
        except (DeviceError, KeyError, TypeError, OSError, AttributeError):
            return DeviceStatus(online=False, on=None)
        return DeviceStatus(online=True, on=bool(value), timer=self._timer_left(reported))
