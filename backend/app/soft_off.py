"""Apagado suave de dispositivos de audio y desvanecimiento antes del temporizador.

Cortar la corriente con música sonando hace "pop" en los parlantes: se pausa primero
y se apaga después. Todo se hace encolando órdenes de media (la cola es thread-safe).
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.devices.base import Device
from app.media import CommandQueue, MediaCommand
from app.now_playing import NowPlaying

PAUSE_WAIT_S = 1.5  # tiempo para que la pausa llegue al panel antes de cortar
MIN_FADE_TIMER_S = 120  # con menos de 2 min no hay desvanecimiento
FADE_LEAD_S = 60
FADE_DURATION_S = 45
FADE_RESTORE_WAIT_S = 2
# Los 16 escalones de volumen de Android (0..15) expresados en porcentaje
ANDROID_STEPS = [round(k / 15 * 100) for k in range(16)]

TimerFactory = Callable[..., Any]  # (intervalo, función, args=[...]) -> objeto con start/cancel


def _default_timer(interval: float, function: Callable[..., None], args: list[Any]) -> Any:
    timer = threading.Timer(interval, function, args=args)
    timer.daemon = True
    return timer


@dataclass
class _Job:
    timer: Any
    cancelled: threading.Event = field(default_factory=threading.Event)


class FadeScheduler:
    """Programa un desvanecimiento de volumen que termina justo antes del temporizador."""

    def __init__(
        self,
        queue: CommandQueue,
        now_playing: NowPlaying,
        lead: float = FADE_LEAD_S,
        sleep: Callable[[float], None] = time.sleep,
        timer_factory: TimerFactory = _default_timer,
    ) -> None:
        self._queue = queue
        self._np = now_playing
        self._lead = lead
        self._sleep = sleep
        self._timer_factory = timer_factory
        self._jobs: dict[str, _Job] = {}
        self._lock = threading.Lock()

    def schedule(self, device_id: str, seconds: int) -> None:
        """Reemplaza el desvanecimiento del dispositivo; sin él si el temporizador es corto."""
        self.cancel(device_id)
        if seconds < MIN_FADE_TIMER_S:
            return
        job = _Job(timer=None)
        job.timer = self._timer_factory(seconds - self._lead, self._run, [device_id, job])
        with self._lock:
            self._jobs[device_id] = job
        job.timer.start()

    def cancel(self, device_id: str) -> None:
        with self._lock:
            job = self._jobs.pop(device_id, None)
        if job is not None:
            job.cancelled.set()
            job.timer.cancel()

    def shutdown(self) -> None:
        for device_id in list(self._jobs):
            self.cancel(device_id)

    def _run(self, device_id: str, job: _Job) -> None:
        with self._lock:
            if self._jobs.get(device_id) is job:
                del self._jobs[device_id]
        volume = self._np.volume
        if job.cancelled.is_set() or not self._np.playing or volume is None:
            return
        levels = [v for v in reversed(ANDROID_STEPS) if v < volume]
        pause = FADE_DURATION_S / len(levels) if levels else 0
        for level in levels:
            self._queue.add(MediaCommand(action="volume", value=level))
            self._sleep(pause)
            if job.cancelled.is_set():
                # Se cancela a medias (p. ej. se apagó a mano): deja el volumen como estaba
                self._queue.add(MediaCommand(action="volume", value=volume))
                return
        self._queue.add(MediaCommand(action="pause"))
        self._sleep(FADE_RESTORE_WAIT_S)
        self._queue.add(MediaCommand(action="volume", value=volume))


class SoftPower:
    """Apaga y programa temporizadores cuidando a los dispositivos de audio."""

    def __init__(
        self,
        queue: CommandQueue,
        now_playing: NowPlaying,
        fade: FadeScheduler,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._queue = queue
        self._np = now_playing
        self.fade = fade
        self._sleep = sleep

    def off(self, device: Device, hard: bool = False) -> None:
        self.fade.cancel(device.id)
        if device.audio and not hard and self._np.playing:
            self._queue.add(MediaCommand(action="pause"))
            self._sleep(PAUSE_WAIT_S)
        device.off()

    def set_timer(self, device: Device, minutes: int) -> None:
        device.set_timer(minutes * 60)  # si falla, no se programa el desvanecimiento
        if device.audio:
            self.fade.schedule(device.id, minutes * 60)
        else:
            self.fade.cancel(device.id)
