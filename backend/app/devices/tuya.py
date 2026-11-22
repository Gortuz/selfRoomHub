"""Adaptador Tuya / Smart Life con tinytuya."""

import threading
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
        client: Any = None,
    ):
        self.id = id
        self.name = name
        self.device_id = device_id
        self.address = address
        self.local_key = local_key
        self.version = float(version)
        self.switch_dp = switch_dp
        self._client = client  # inyectable para tests
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

    def status(self) -> DeviceStatus:
        try:
            with self._lock:
                result = self.client.status()
            self._raise_on_error(result)
            value = result["dps"][str(self.switch_dp)]
        except (DeviceError, KeyError, TypeError, OSError):
            return DeviceStatus(online=False, on=None)
        return DeviceStatus(online=True, on=bool(value))
