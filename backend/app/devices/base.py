"""Interfaz común de dispositivos."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LightStatus:
    """Estado de un foco. color_temp es None en modo color; hue/saturation, en modo blanco."""

    brightness: int | None = None  # 1..100
    color_temp: int | None = None  # kelvin
    hue: int | None = None  # 0..360
    saturation: int | None = None  # 0..100
    color_temp_range: tuple[int, int] | None = None  # None: sin temperatura ajustable
    color: bool = False  # admite hue/saturation


@dataclass
class DeviceStatus:
    online: bool
    on: bool | None
    timer: int | None = None  # segundos que faltan para el apagado programado
    light: LightStatus | None = None  # solo focos


class DeviceError(Exception):
    """Fallo al comunicarse con un dispositivo."""


class Device(ABC):
    id: str
    name: str
    audio: bool = False  # alimenta parlantes: se apaga con pausa previa

    @abstractmethod
    def on(self) -> None: ...

    @abstractmethod
    def off(self) -> None: ...

    @abstractmethod
    def status(self) -> DeviceStatus: ...

    def set_timer(self, seconds: int) -> None:
        """Cuenta regresiva que apaga el dispositivo; 0 la cancela."""
        raise NotImplementedError(f"{self.id} no tiene temporizador")

    def set_light(
        self,
        brightness: int | None = None,
        color_temp: int | None = None,
        hue: int | None = None,
        saturation: int | None = None,
    ) -> None:
        """Ajusta brillo, temperatura (K) o color, y enciende. ValueError si el foco no puede."""
        raise NotImplementedError(f"{self.id} no es un foco regulable")
