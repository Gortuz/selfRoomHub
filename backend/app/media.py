"""Cola en memoria de órdenes de reproducción y volumen para la app kiosco."""

import asyncio
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

TTL_S = 10.0
MAX_QUEUED = 50
MAX_QUERY = 200


class MediaCommand(BaseModel):
    action: Literal[
        "toggle", "play", "pause", "next", "previous", "volume", "play_search", "wake", "launch"
    ]
    value: int | None = Field(default=None, ge=0, le=100)
    query: str | None = Field(default=None, max_length=MAX_QUERY)
    focus: Literal["artist", "album", "playlist", "any"] | None = None
    # launch: paquete Android a abrir (p. ej. com.spotify.music)
    package: str | None = Field(
        default=None, max_length=100, pattern=r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)+$"
    )

    @model_validator(mode="after")
    def check_fields(self) -> Self:
        if self.action == "volume" and self.value is None:
            raise ValueError("volume exige value (0-100)")
        if self.action != "volume" and self.value is not None:
            raise ValueError("value solo se admite con volume")
        if self.action == "play_search":
            if self.query is None or not self.query.strip():
                raise ValueError("play_search exige query no vacía")
            if self.focus is None:
                self.focus = "any"
        elif self.query is not None or self.focus is not None:
            raise ValueError("query y focus solo se admiten con play_search")
        if self.action == "launch" and not self.package:
            raise ValueError("launch exige package")
        if self.action != "launch" and self.package is not None:
            raise ValueError("package solo se admite con launch")
        return self


@dataclass
class QueuedCommand:
    id: int
    action: str
    value: int | None
    created_at: str
    expires_at: float  # monotonic
    query: str | None = None
    focus: str | None = None
    package: str | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "id": self.id,
            "action": self.action,
            "value": self.value,
            "query": self.query,
            "focus": self.focus,
            "package": self.package,
            "created_at": self.created_at,
        }


class CommandQueue:
    def __init__(
        self,
        ttl: float = TTL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl
        self._clock = clock
        self._items: deque[QueuedCommand] = deque(maxlen=MAX_QUEUED)
        self._last_id = 0
        # Un evento por esperador: así funciona aunque cada petición use otro loop
        self._waiters: list[tuple[asyncio.AbstractEventLoop, asyncio.Event]] = []
        # `add` también se llama desde hilos (escenas en el threadpool): el lock lo hace seguro
        self._lock = threading.Lock()

    def add(self, command: MediaCommand) -> int:
        with self._lock:
            self._last_id += 1
            self._items.append(
                QueuedCommand(
                    id=self._last_id,
                    action=command.action,
                    value=command.value,
                    created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                    expires_at=self._clock() + self._ttl,
                    query=command.query,
                    focus=command.focus,
                    package=command.package,
                )
            )
            new_id = self._last_id
            waiters = list(self._waiters)
        for loop, event in waiters:
            loop.call_soon_threadsafe(event.set)
        return new_id

    def after(self, after: int) -> list[QueuedCommand]:
        now = self._clock()
        with self._lock:
            return [c for c in self._items if c.id > after and c.expires_at > now]

    async def wait_after(self, after: int, timeout: float) -> list[QueuedCommand]:
        """Como `after`, pero espera hasta `timeout` s si aún no hay órdenes."""
        found = self.after(after)
        if found or timeout <= 0:
            return found
        event = asyncio.Event()
        entry = (asyncio.get_running_loop(), event)
        with self._lock:
            self._waiters.append(entry)
        try:
            await asyncio.wait_for(event.wait(), timeout)
        except TimeoutError:
            pass
        finally:
            with self._lock:
                self._waiters.remove(entry)
        return self.after(after)
