"""Estado en memoria de lo que suena en el servidor (lo publica la app kiosco)."""

import base64
import binascii
import hashlib
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel

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
    updated_at: str | None = None

    def update(self, body: NowPlayingUpdate) -> None:
        # Valida primero para no dejar el estado a medias si la imagen falla
        new_art = decode_art(body.art_base64) if body.art_base64 else None
        if new_art is not None:
            self.art, self.art_type = new_art
        elif not body.playing or (body.title, body.artist) != (self.title, self.artist):
            self.art = self.art_type = None
        if body.playing:
            self.title, self.artist = body.title, body.artist
            self.album, self.app = body.album, body.app
        else:
            self.title = self.artist = self.album = self.app = None
        self.playing = body.playing
        self.updated_at = datetime.now().astimezone().isoformat(timespec="seconds")

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
            "updated_at": self.updated_at,
        }
