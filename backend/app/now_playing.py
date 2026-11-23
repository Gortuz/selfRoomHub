"""Estado en memoria de lo que suena en el servidor (lo publica la app kiosco)."""

import base64
import binascii
import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from pydantic import BaseModel, Field

MAX_ART_BYTES = 2 * 1024 * 1024


class ArtError(ValueError):
    """Imagen inválida (base64 roto, demasiado grande o tipo desconocido)."""


class NowPlayingUpdate(BaseModel):
    playing: bool
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    app: str | None = None
    art_base64: str | None = None
    volume: int | None = Field(default=None, ge=0, le=100)
    position_ms: int | None = Field(default=None, ge=0)
    duration_ms: int | None = Field(default=None, ge=0)
    position_at: int | None = None  # epoch en ms de la medición
    speed: float | None = None  # 1.0 si no viene


def _now_ms() -> int:
    return int(time.time() * 1000)


def decode_art(data: str) -> tuple[bytes, str]:
    """Decodifica la portada y detecta su tipo por firma."""
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as e:
        raise ArtError("art_base64 no es base64 válido") from e
    if len(raw) > MAX_ART_BYTES:
        raise ArtError("La imagen supera 2 MB")
    if raw.startswith(b"\xff\xd8\xff"):
        return raw, "image/jpeg"
    if raw.startswith(b"\x89PNG"):
        return raw, "image/png"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return raw, "image/webp"
    raise ArtError("Tipo de imagen no soportado (JPEG, PNG o WEBP)")


@dataclass
class NowPlaying:
    playing: bool = False
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    app: str | None = None
    art: bytes | None = None
    art_type: str | None = None
    volume: int | None = None
    updated_at: str | None = None
    position_ms: int | None = None
    duration_ms: int | None = None
    position_at: int | None = None
    speed: float = 1.0
    clock: Callable[[], int] = field(default=_now_ms, repr=False)  # epoch en ms

    def update(self, body: NowPlayingUpdate) -> None:
        # Valida primero para no dejar el estado a medias si la imagen falla
        new_art = decode_art(body.art_base64) if body.art_base64 else None
        if new_art is not None:
            self.art, self.art_type = new_art
        elif not body.playing or (body.title, body.artist) != (self.title, self.artist):
            self.art = self.art_type = None
        # Canción distinta (o pausa): la posición anterior ya no vale
        reset = not body.playing or (body.title, body.artist) != (self.title, self.artist)
        if reset:
            self.position_ms = self.duration_ms = self.position_at = None
            self.speed = 1.0
        if body.position_ms is not None:
            self.position_ms = body.position_ms
        if body.duration_ms is not None:
            self.duration_ms = body.duration_ms
        if body.position_at is not None:
            self.position_at = body.position_at
        if body.speed is not None:
            self.speed = body.speed
        if body.playing:
            self.title, self.artist = body.title, body.artist
            self.album, self.app = body.album, body.app
        else:
            self.title = self.artist = self.album = self.app = None
        # Sin volumen en el PUT se conserva el último conocido
        if body.volume is not None:
            self.volume = body.volume
        self.playing = body.playing
        self.updated_at = datetime.now().astimezone().isoformat(timespec="seconds")

    def current_position_ms(self) -> int | None:
        """Posición extrapolada a este momento, acotada a la duración."""
        if self.position_ms is None:
            return None
        pos = float(self.position_ms)
        if self.playing and self.position_at is not None:
            pos += (self.clock() - self.position_at) * self.speed
        pos = max(pos, 0.0)
        if self.duration_ms is not None:
            pos = min(pos, float(self.duration_ms))
        return int(pos)

    def to_json(self) -> dict[str, object]:
        art_url = None
        if self.art is not None:
            art_url = f"/now-playing/art?v={hashlib.sha1(self.art).hexdigest()[:8]}"
        return {
            "playing": self.playing,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "app": self.app,
            "art_url": art_url,
            "volume": self.volume,
            "position_ms": self.current_position_ms(),
            "duration_ms": self.duration_ms,
            "updated_at": self.updated_at,
        }
