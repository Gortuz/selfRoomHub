"""Cola en memoria de órdenes de reproducción y volumen para la app kiosco."""

import asyncio
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

TTL_S = 10.0
MAX_QUEUED = 50


class MediaCommand(BaseModel):
    action: Literal["toggle", "play", "pause", "next", "previous", "volume"]
    value: int | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def check_value(self) -> Self:
        if self.action == "volume" and self.value is None:
            raise ValueError("volume exige value (0-100)")
        if self.action != "volume" and self.value is not None:
            raise ValueError("value solo se admite con volume")
        return self


@dataclass
class QueuedCommand:
    id: int
    action: str
    value: int | None
    created_at: str
    expires_at: float  # monotonic

    def to_json(self) -> dict[str, object]:
        return {
            "id": self.id,
            "action": self.action,
            "value": self.value,
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

    def add(self, command: MediaCommand) -> int:
        self._last_id += 1
        self._items.append(
            QueuedCommand(
                id=self._last_id,
                action=command.action,
                value=command.value,
                created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                expires_at=self._clock() + self._ttl,
            )
        )
        for loop, event in self._waiters:
            loop.call_soon_threadsafe(event.set)
        return self._last_id

    def after(self, after: int) -> list[QueuedCommand]:
        now = self._clock()
        return [c for c in self._items if c.id > after and c.expires_at > now]

    async def wait_after(self, after: int, timeout: float) -> list[QueuedCommand]:
        """Como `after`, pero espera hasta `timeout` s si aún no hay órdenes."""
        found = self.after(after)
        if found or timeout <= 0:
            return found
        event = asyncio.Event()
        entry = (asyncio.get_running_loop(), event)
        self._waiters.append(entry)
        try:
            await asyncio.wait_for(event.wait(), timeout)
        except TimeoutError:
            pass
        finally:
            self._waiters.remove(entry)
        return self.after(after)
