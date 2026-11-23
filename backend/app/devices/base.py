"""Interfaz común de dispositivos."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class DeviceStatus:
    online: bool
    on: bool | None


class DeviceError(Exception):
    """Fallo al comunicarse con un dispositivo."""


class Device(ABC):
    id: str
    name: str

    @abstractmethod
    def on(self) -> None: ...

    @abstractmethod
    def off(self) -> None: ...

    @abstractmethod
    def status(self) -> DeviceStatus: ...

    def set_timer(self, seconds: int) -> None:
        """Cuenta regresiva que apaga el dispositivo; 0 la cancela."""
        raise NotImplementedError(f"{self.id} no tiene temporizador")
