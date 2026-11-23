"""Modo día/noche: sigue un horario y puede forzarse hasta el próximo cambio del horario."""

import os
import re
from collections.abc import Callable
from datetime import datetime, time, timedelta

MODES = ("day", "night")
_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def parse_hhmm(value: object) -> time:
    """Convierte 'HH:MM' (24 h) a time; lanza ValueError si el formato no es válido."""
    match = _HHMM.match(value) if isinstance(value, str) else None
    if match is None:
        raise ValueError(f"Hora inválida {value!r} (formato HH:MM)")
    return time(int(match.group(1)), int(match.group(2)))


def in_window(start: time, end: time, now: time) -> bool:
    """start inclusivo, end exclusivo; start > end cruza la medianoche."""
    if start < end:
        return start <= now < end
    return now >= start or now < end


class ModeState:
    def __init__(
        self,
        night_from: str = "23:00",
        night_to: str = "06:00",
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._from = parse_hhmm(night_from)
        self._to = parse_hhmm(night_to)
        if self._from == self._to:
            raise ValueError("night_from y night_to no pueden ser iguales")
        self._clock = clock
        self._forced: str | None = None
        self._until: datetime | None = None

    @classmethod
    def from_env(cls, clock: Callable[[], datetime] = datetime.now) -> "ModeState":
        return cls(
            os.environ.get("SELFROOMHUB_NIGHT_FROM", "23:00"),
            os.environ.get("SELFROOMHUB_NIGHT_TO", "06:00"),
            clock,
        )

    def schedule_mode(self, now: datetime) -> str:
        return "night" if in_window(self._from, self._to, now.time()) else "day"

    def _next_boundary(self, now: datetime) -> datetime:
        candidates = []
        for t in (self._from, self._to):
            at = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
            candidates.append(at if at > now else at + timedelta(days=1))
        return min(candidates)

    def set(self, mode: str) -> None:
        if mode == "auto":
            self._forced = self._until = None
        elif mode in MODES:
            self._forced = mode
            self._until = self._next_boundary(self._clock())
        else:
            raise ValueError(f"Modo inválido {mode!r} (day, night o auto)")

    def current(self) -> dict[str, str]:
        now = self._clock()
        if self._forced and self._until and now < self._until:
            return {"mode": self._forced, "source": "scene"}
        self._forced = self._until = None
        return {"mode": self.schedule_mode(now), "source": "schedule"}
