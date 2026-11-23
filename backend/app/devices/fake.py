"""Dispositivo en memoria para tests y pruebas sin hardware."""

from app.devices.base import Device, DeviceError, DeviceStatus


class FakeDevice(Device):
    def __init__(self, id: str, name: str, initially_on: bool = False, online: bool = True):
        self.id = id
        self.name = name
        self._on = initially_on
        self.online = online
        self.timer: int | None = None

    def _check(self) -> None:
        if not self.online:
            raise DeviceError(f"{self.id} está fuera de línea")

    def on(self) -> None:
        self._check()
        self._on = True

    def off(self) -> None:
        self._check()
        self._on = False

    def status(self) -> DeviceStatus:
        if not self.online:
            return DeviceStatus(online=False, on=None)
        return DeviceStatus(online=True, on=self._on)

    def set_timer(self, seconds: int) -> None:
        self._check()
        self.timer = seconds
