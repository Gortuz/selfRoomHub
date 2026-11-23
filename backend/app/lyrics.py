"""Letras desde LRCLIB (https://lrclib.net), con caché en memoria."""

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from collections.abc import Callable

BASE_URL = "https://lrclib.net/api"
USER_AGENT = "selfRoomHub (https://github.com/Gortuz/selfRoomHub)"
TIMEOUT_S = 8
CACHE_SIZE = 50

# Fetcher: URL -> JSON ya decodificado, o None si LRCLIB responde 404
LyricsFetcher = Callable[[str], object]

_TIME_TAG = re.compile(r"\[(\d+):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_VERSION_SEP = re.compile(r"\s[-–—]\s")
_TRAILING_GROUP = re.compile(r"\s*[(\[][^)\]]*[)\]]\s*$")


class LyricsUnavailable(Exception):
    """LRCLIB no respondió (red, timeout o respuesta inválida)."""


def fetch_json(url: str) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise LyricsUnavailable(f"LRCLIB respondió {e.code}") from e
    except (OSError, ValueError) as e:  # URLError y timeout son OSError
        raise LyricsUnavailable(f"LRCLIB no responde: {e}") from e


def parse_lrc(text: str) -> list[dict[str, object]]:
    """Convierte LRC en [{"t": ms, "line": str}] ordenado; ignora metadatos."""
    out: list[dict[str, object]] = []
    for raw in text.splitlines():
        tags = []
        pos = 0
        while m := _TIME_TAG.match(raw, pos):
            tags.append(m)
            pos = m.end()
        if not tags:
            continue
        line = raw[pos:].strip()
        for m in tags:
            frac = int((m.group(3) or "0").ljust(3, "0"))
            out.append({"t": (int(m.group(1)) * 60 + int(m.group(2))) * 1000 + frac, "line": line})
    out.sort(key=lambda x: x["t"])  # type: ignore[arg-type,return-value]
    return out


def strip_version(title: str) -> str:
    """Quita el sufijo de versión: ' - Remastered', ' (Live)', ' [2011]'."""
    base = _VERSION_SEP.split(title, maxsplit=1)[0]
    return _TRAILING_GROUP.sub("", base).strip()


def _to_lyrics(data: object) -> dict[str, object] | None:
    if not isinstance(data, dict):
        return None
    synced_raw = data.get("syncedLyrics")
    synced = parse_lrc(synced_raw) if isinstance(synced_raw, str) else []
    plain = data.get("plainLyrics")
    plain = plain if isinstance(plain, str) and plain.strip() else None
    instrumental = bool(data.get("instrumental"))
    if not synced and plain is None and not instrumental:
        return None
    return {"synced": synced or None, "plain": plain, "instrumental": instrumental}


class LyricsClient:
    def __init__(self, fetcher: LyricsFetcher | None = None) -> None:
        self._fetch = fetcher or fetch_json
        self._cache: OrderedDict[tuple[str, str, str], dict[str, object] | None] = OrderedDict()

    def lookup(
        self,
        title: str,
        artist: str | None,
        album: str | None = None,
        duration_ms: int | None = None,
    ) -> dict[str, object] | None:
        """Letra de la canción, o None si no hay. Lanza LyricsUnavailable si falla la red."""
        key = (title, artist or "", album or "")
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        result = self._search(title, artist or "", album, duration_ms)
        self._cache[key] = result  # también guarda "sin letra"
        if len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)
        return result

    def _get(
        self, title: str, artist: str, album: str | None, duration_ms: int | None
    ) -> dict[str, object] | None:
        params = {"track_name": title, "artist_name": artist}
        if album:
            params["album_name"] = album
        if duration_ms:
            params["duration"] = str(round(duration_ms / 1000))
        return _to_lyrics(self._fetch(f"{BASE_URL}/get?{urllib.parse.urlencode(params)}"))

    def _search(
        self, title: str, artist: str, album: str | None, duration_ms: int | None
    ) -> dict[str, object] | None:
        found = self._get(title, artist, album, duration_ms)
        if found:
            return found
        short = strip_version(title)
        if short and short != title:
            found = self._get(short, artist, album, duration_ms)
            if found:
                return found
        query = urllib.parse.urlencode({"track_name": title, "artist_name": artist})
        results = self._fetch(f"{BASE_URL}/search?{query}")
        if isinstance(results, list) and results:
            return _to_lyrics(results[0])
        return None
