"""Cliente de la Spotify Web API con PKCE, para reproducir en un dispositivo Connect.

Sin dependencias: urllib para la red. El transporte (`fetch`) y el reloj son
inyectables para probar sin internet.
"""

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_URL = "https://api.spotify.com/v1"
SCOPES = "user-read-playback-state user-modify-playback-state user-read-currently-playing"
DEFAULT_REDIRECT = "http://127.0.0.1:8000/spotify/callback"
DEFAULT_TOKEN_FILE = "~/.local/state/selfroomhub/spotify.json"
STATE_TTL_S = 600
REFRESH_MARGIN_S = 60
TIMEOUT_S = 10
TYPES = ("artist", "album", "playlist", "track")

Fetch = Callable[[str, str, dict[str, str], bytes | None], tuple[int, bytes]]


class SpotifyError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class DeviceNotFound(SpotifyError):
    """El dispositivo Connect no aparece (app cerrada o dormida)."""

    def __init__(self, message: str) -> None:
        super().__init__(404, message)


def urllib_fetch(
    method: str, url: str, headers: dict[str, str], data: bytes | None
) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise SpotifyError(502, f"No se pudo contactar con Spotify: {e}") from e


def _norm(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold().strip()


def _error_message(body: bytes) -> str:
    try:
        data = json.loads(body)
    except ValueError:
        return body.decode(errors="replace")[:200] or "sin detalle"
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, dict):
        return str(err.get("message") or err)
    if isinstance(data, dict) and data.get("error_description"):
        return str(data["error_description"])
    return str(err or data)


class SpotifyClient:
    def __init__(
        self,
        client_id: str | None,
        redirect_uri: str = DEFAULT_REDIRECT,
        device: str | None = None,
        token_file: Path | str = DEFAULT_TOKEN_FILE,
        fetch: Fetch = urllib_fetch,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.client_id = client_id or None
        self.redirect_uri = redirect_uri
        self.device = device or None
        self.token_file = Path(token_file).expanduser()
        self._fetch = fetch
        self._clock = clock
        self._lock = threading.RLock()
        self._pending: dict[str, tuple[str, float]] = {}  # state -> (verifier, expira)

    @classmethod
    def from_env(cls) -> "SpotifyClient":
        env = os.environ
        return cls(
            env.get("SELFROOMHUB_SPOTIFY_CLIENT_ID"),
            env.get("SELFROOMHUB_SPOTIFY_REDIRECT_URI") or DEFAULT_REDIRECT,
            env.get("SELFROOMHUB_SPOTIFY_DEVICE"),
            env.get("SELFROOMHUB_SPOTIFY_TOKEN_FILE") or DEFAULT_TOKEN_FILE,
        )

    @property
    def configured(self) -> bool:
        return self.client_id is not None

    @property
    def linked(self) -> bool:
        return self.configured and bool(self._load().get("refresh_token"))

    def _require_configured(self) -> str:
        if self.client_id is None:
            raise SpotifyError(409, "Spotify no configurado")
        return self.client_id

    # --- Almacén de tokens ---

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.token_file.read_text())
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict[str, Any]) -> None:
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.token_file.with_name(self.token_file.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.token_file)

    # --- PKCE ---

    def login_url(self) -> str:
        client_id = self._require_configured()
        verifier = secrets.token_urlsafe(64)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        state = secrets.token_urlsafe(16)
        now = self._clock()
        with self._lock:
            self._pending = {s: v for s, v in self._pending.items() if v[1] > now}
            self._pending[state] = (verifier, now + STATE_TTL_S)
        query = urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": client_id,
                "scope": SCOPES,
                "redirect_uri": self.redirect_uri,
                "state": state,
                "code_challenge_method": "S256",
                "code_challenge": challenge,
            }
        )
        return f"{AUTH_URL}?{query}"

    def handle_callback(self, code: str, state: str) -> None:
        client_id = self._require_configured()
        with self._lock:
            entry = self._pending.pop(state, None)
        if entry is None or entry[1] <= self._clock():
            raise SpotifyError(400, "State inválido o expirado: vuelve a iniciar el vínculo")
        self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "client_id": client_id,
                "code_verifier": entry[0],
            }
        )

    def _token_request(self, form: dict[str, str]) -> dict[str, Any]:
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        status, body = self._fetch(
            "POST", TOKEN_URL, headers, urllib.parse.urlencode(form).encode()
        )
        if status != 200:
            raise SpotifyError(400 if status in (400, 401) else 502, _error_message(body))
        data = json.loads(body)
        with self._lock:
            saved = self._load()
            saved["access_token"] = data["access_token"]
            saved["expires_at"] = self._clock() + float(data.get("expires_in", 3600))
            # Spotify puede devolver un refresh_token nuevo; si no, se conserva el actual
            saved["refresh_token"] = data.get("refresh_token") or saved.get("refresh_token")
            self._save(saved)
            return saved

    def _access_token(self, force: bool = False) -> str:
        self._require_configured()
        with self._lock:
            saved = self._load()
            refresh = saved.get("refresh_token")
            if not refresh:
                raise SpotifyError(409, "Spotify no vinculado: abre /spotify/login")
            fresh = saved.get("expires_at", 0) - self._clock() > REFRESH_MARGIN_S
            if saved.get("access_token") and fresh and not force:
                return str(saved["access_token"])
            saved = self._token_request(
                {
                    "grant_type": "refresh_token",
                    "refresh_token": refresh,
                    "client_id": self.client_id or "",
                }
            )
            return str(saved["access_token"])

    # --- API ---

    def api(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        url = API_URL + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        for attempt in (0, 1):
            headers = {"Authorization": f"Bearer {self._access_token(force=attempt == 1)}"}
            if data is not None:
                headers["Content-Type"] = "application/json"
            status, raw = self._fetch(method, url, headers, data)
            if status == 401 and attempt == 0:
                continue
            break
        if status == 204 or (status < 300 and not raw):
            return None
        if status >= 300:
            raise SpotifyError(status, _error_message(raw))
        return json.loads(raw)

    def devices(self) -> list[dict[str, Any]]:
        data = self.api("GET", "/me/player/devices")
        return list((data or {}).get("devices") or [])

    def find_device(self, name: str | None = None) -> dict[str, Any]:
        found = self.devices()
        names = ", ".join(str(d.get("name")) for d in found) or "(ninguno)"
        if name:
            wanted = _norm(name)
            hit = next((d for d in found if _norm(str(d.get("name", ""))) == wanted), None)
            hit = hit or next((d for d in found if wanted in _norm(str(d.get("name", "")))), None)
        else:
            hit = next((d for d in found if d.get("is_active")), None) or next(
                (d for d in found if d.get("type") == "Smartphone"), None
            )
        if hit is None:
            what = f"Dispositivo Spotify no encontrado: {name}" if name else "Sin dispositivo"
            raise DeviceNotFound(f"{what}. Disponibles: {names}")
        return hit

    def search_uri(self, query: str, type: str = "artist") -> str:
        if type not in TYPES:
            raise SpotifyError(422, f"Tipo inválido: {type}")
        data = self.api(
            "GET",
            "/search",
            {"q": query, "type": type, "limit": 1, "market": "from_token"},
        )
        items = ((data or {}).get(type + "s") or {}).get("items") or []
        items = [i for i in items if i]
        if not items:
            raise SpotifyError(404, f"Spotify no encontró {type}: {query}")
        return str(items[0]["uri"])

    def play(
        self,
        query: str | None = None,
        uri: str | None = None,
        type: str = "artist",
        device: str | None = None,
        shuffle: bool | None = None,
    ) -> dict[str, Any]:
        if not uri and not query:
            raise SpotifyError(422, "Falta query o uri")
        if uri:
            parts = uri.split(":")
            if len(parts) == 3 and parts[1] in TYPES:
                type = parts[1]
        else:
            uri = self.search_uri(query or "", type)
        target = self.find_device(device or self.device)
        device_id = target["id"]
        if shuffle is not None:
            self.api(
                "PUT",
                "/me/player/shuffle",
                {"state": "true" if shuffle else "false", "device_id": device_id},
            )
        payload = {"uris": [uri]} if type == "track" else {"context_uri": uri}
        self.api("PUT", "/me/player/play", {"device_id": device_id}, payload)
        return {"uri": uri, "device": target.get("name"), "type": type}
