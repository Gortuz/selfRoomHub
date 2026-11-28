"""Adaptador TP-Link Tapo / Kasa con python-kasa (focos y enchufes).

python-kasa es asíncrono y el backend atiende en hilos: cada dispositivo tiene su propio
bucle asyncio en un hilo y mantiene la sesión abierta entre órdenes.
"""

import asyncio
import concurrent.futures
import contextlib
import threading
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from kasa import Credentials, Discover, KasaException, Module
from kasa.interfaces.light import LightState

from app.devices.base import Device, DeviceError, DeviceStatus, LightStatus

T = TypeVar("T")
ERRORS = (KasaException, OSError, asyncio.TimeoutError)


class TapoDevice(Device):
    def __init__(
        self,
        id: str,
        name: str,
        address: str,
        username: str,
        password: str,
        timeout: float = 5.0,
        connect: Callable[[], Awaitable[Any]] | None = None,
    ):
        self.id = id
        self.name = name
        self.address = address
        self.username = username
        self.password = password
        self.timeout = timeout
        self._connect = connect or self._discover  # inyectable para tests
        self._dev: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

    async def _discover(self) -> Any:
        # Descubre protocolo y cifrado (KLAP, AES...) preguntándole al propio dispositivo
        dev = await Discover.discover_single(
            self.address,
            credentials=Credentials(self.username, self.password),
            discovery_timeout=max(1, round(self.timeout)),
            timeout=max(1, round(self.timeout)),
        )
        if dev is None:
            raise KasaException(f"{self.address} no respondió al descubrimiento")
        await dev.update()  # sin esto no hay módulos (luz) hasta la primera consulta
        return dev

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            loop = asyncio.new_event_loop()
            threading.Thread(target=loop.run_forever, name=f"tapo-{self.id}", daemon=True).start()
            self._loop = loop
        return self._loop

    async def _drop(self) -> None:
        dev, self._dev = self._dev, None
        if dev is not None:
            with contextlib.suppress(Exception):
                await dev.disconnect()

    async def _call(self, fn: Callable[[Any], Awaitable[T]]) -> T:
        # Un reintento con conexión nueva: la sesión pudo caducar o el foco cambió de estado
        for attempt in range(2):
            try:
                if self._dev is None:
                    self._dev = await self._connect()
                return await fn(self._dev)
            except ERRORS as e:
                await self._drop()
                if attempt:
                    raise DeviceError(f"{self.id}: {e}") from e
        raise AssertionError("inalcanzable")

    def _run(self, fn: Callable[[Any], Awaitable[T]]) -> T:
        with self._lock:
            loop = self._ensure_loop()
            fut = asyncio.run_coroutine_threadsafe(self._call(fn), loop)
            try:
                # descubrimiento + petición, con un reintento
                return fut.result(timeout=self.timeout * 4)
            except concurrent.futures.TimeoutError as e:
                fut.cancel()
                asyncio.run_coroutine_threadsafe(self._drop(), loop)
                raise DeviceError(f"{self.id}: sin respuesta") from e

    def on(self) -> None:
        self._run(lambda dev: dev.turn_on())

    def off(self) -> None:
        self._run(lambda dev: dev.turn_off())

    def status(self) -> DeviceStatus:
        async def read(dev: Any) -> tuple[bool, LightStatus | None]:
            await dev.update()
            return bool(dev.is_on), _light_status(dev)

        try:
            on, light = self._run(read)
        except DeviceError:
            return DeviceStatus(online=False, on=None)
        return DeviceStatus(online=True, on=on, light=light)

    def set_light(
        self,
        brightness: int | None = None,
        color_temp: int | None = None,
        hue: int | None = None,
        saturation: int | None = None,
    ) -> None:
        async def apply(dev: Any) -> None:
            light = dev.modules[Module.Light] if Module.Light in dev.modules else None
            if light is None:
                raise NotImplementedError(f"{self.id} no es un foco regulable")
            if brightness is not None and not light.has_feature("brightness"):
                raise ValueError(f"{self.id} no regula el brillo")
            if color_temp is not None:
                if not light.has_feature("color_temp"):
                    raise ValueError(f"{self.id} no ajusta la temperatura de color")
                r = light.valid_temperature_range
                if not r.min <= color_temp <= r.max:
                    raise ValueError(f"{self.id}: temperatura fuera de {r.min}..{r.max} K")
            if hue is not None and not light.has_feature("hsv"):
                raise ValueError(f"{self.id} no admite color")
            state = LightState(
                light_on=True,
                brightness=brightness,
                # Tapo pasa a modo color cuando color_temp es 0
                color_temp=0 if hue is not None else color_temp,
                hue=hue,
                saturation=saturation,
            )
            await light.set_state(state)

        self._run(apply)


def _light_status(dev: Any) -> LightStatus | None:
    if Module.Light not in dev.modules:
        return None
    light = dev.modules[Module.Light]
    ct_range, ct = None, None
    if light.has_feature("color_temp"):
        r = light.valid_temperature_range
        ct_range = (r.min, r.max)
        ct = light.color_temp or None
    color = light.has_feature("hsv")
    hue = sat = None
    if color and ct is None:
        hue, sat = light.hsv.hue, light.hsv.saturation
    return LightStatus(
        brightness=light.brightness if light.has_feature("brightness") else None,
        color_temp=ct,
        hue=hue,
        saturation=sat,
        color_temp_range=ct_range,
        color=color,
    )
