"""Dispositivo en memoria para tests y pruebas sin hardware."""

from app.devices.base import Device, DeviceError, DeviceStatus, LightStatus

FAKE_CT_RANGE = (2500, 6500)


class FakeDevice(Device):
    def __init__(
        self,
        id: str,
        name: str,
        initially_on: bool = False,
        online: bool = True,
        light: bool = False,  # simula un foco con temperatura y color
    ):
        self.id = id
        self.name = name
        self._on = initially_on
        self.online = online
        self.timer: int | None = None
        self.light = (
            LightStatus(100, 2700, color_temp_range=FAKE_CT_RANGE, color=True) if light else None
        )

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
        return DeviceStatus(online=True, on=self._on, light=self.light)

    def set_timer(self, seconds: int) -> None:
        self._check()
        self.timer = seconds

    def set_light(
        self,
        brightness: int | None = None,
        color_temp: int | None = None,
        hue: int | None = None,
        saturation: int | None = None,
    ) -> None:
        if self.light is None:
            raise NotImplementedError(f"{self.id} no es un foco regulable")
        self._check()
        lo, hi = FAKE_CT_RANGE
        if color_temp is not None and not lo <= color_temp <= hi:
            raise ValueError(f"{self.id}: temperatura fuera de {lo}..{hi} K")
        if brightness is not None:
            self.light.brightness = brightness
        if color_temp is not None:
            self.light.color_temp, self.light.hue, self.light.saturation = color_temp, None, None
        if hue is not None:
            self.light.color_temp, self.light.hue, self.light.saturation = None, hue, saturation
        self._on = True
