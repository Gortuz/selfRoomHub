import base64
import hashlib
import json
import stat
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from app.devices.fake import FakeDevice
from app.main import create_app
from app.media import CommandQueue
from app.scenes import SceneContext, parse_scenes, run_scene
from app.spotify import SpotifyClient, SpotifyError
from tests.conftest import HEADERS, TOKEN

PHONE = {"id": "dev1", "name": "Redmi Note 8", "type": "Smartphone", "is_active": False}
SPEAKER = {"id": "dev2", "name": "Sala Ñandú", "type": "Speaker", "is_active": True}


class FakeNet:
    """Transporte falso: responde por (método, ruta) y registra las llamadas."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict, bytes | None]] = []
        self.routes: dict[tuple[str, str], list[tuple[int, object]]] = {}
        self.devices = [PHONE, SPEAKER]

    def on(self, method: str, path: str, *responses: tuple[int, object]) -> None:
        self.routes[(method, path)] = list(responses)

    def __call__(self, method, url, headers, data):
        self.calls.append((method, url, headers, data))
        parsed = urllib.parse.urlparse(url)
        key = (method, parsed.path)
        queue = self.routes.get(key)
        if queue is None:
            if parsed.path.endswith("/me/player/devices"):
                return 200, json.dumps({"devices": self.devices}).encode()
            if method == "PUT":
                return 204, b""
            raise AssertionError(f"ruta no simulada: {key}")
        status, body = queue.pop(0) if len(queue) > 1 else queue[0]
        return status, json.dumps(body).encode() if body is not None else b""

    def paths(self, method=None):
        return [urllib.parse.urlparse(c[1]).path for c in self.calls if method in (None, c[0])]


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def net():
    return FakeNet()


@pytest.fixture
def clock():
    return Clock()


def make(net, clock, tmp_path, **kw):
    return SpotifyClient(
        "cid", token_file=tmp_path / "sub" / "spotify.json", fetch=net, clock=clock, **kw
    )


def link(sp, clock, refresh="r1", access="a1", expires_in=3600):
    sp._save(
        {"refresh_token": refresh, "access_token": access, "expires_at": clock.now + expires_in}
    )


TOKEN_RESP = (200, {"access_token": "acc", "refresh_token": "ref", "expires_in": 3600})


def test_login_url_pkce(net, clock, tmp_path):
    sp = make(net, clock, tmp_path)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(sp.login_url()).query)
    verifier = sp._pending[q["state"][0]][0]
    digest = hashlib.sha256(verifier.encode()).digest()
    assert q["code_challenge"][0] == base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    assert q["code_challenge_method"] == ["S256"]
    assert q["client_id"] == ["cid"]
    assert "user-modify-playback-state" in q["scope"][0]


def test_callback_intercambia_y_guarda(net, clock, tmp_path):
    sp = make(net, clock, tmp_path)
    net.on("POST", "/api/token", TOKEN_RESP)
    state = urllib.parse.parse_qs(urllib.parse.urlparse(sp.login_url()).query)["state"][0]
    verifier = sp._pending[state][0]
    sp.handle_callback("CODE", state)
    method, url, headers, data = net.calls[0]
    form = urllib.parse.parse_qs(data.decode())
    assert url == "https://accounts.spotify.com/api/token"
    assert headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert form["grant_type"] == ["authorization_code"]
    assert form["code"] == ["CODE"] and form["code_verifier"] == [verifier]
    saved = json.loads(sp.token_file.read_text())
    assert saved["refresh_token"] == "ref" and saved["access_token"] == "acc"
    assert saved["expires_at"] == clock.now + 3600
    assert stat.S_IMODE(sp.token_file.stat().st_mode) == 0o600
    assert sp.linked
    # el state es de un solo uso
    with pytest.raises(SpotifyError):
        sp.handle_callback("CODE", state)


def test_state_invalido_y_expirado(net, clock, tmp_path):
    sp = make(net, clock, tmp_path)
    with pytest.raises(SpotifyError) as e:
        sp.handle_callback("c", "nada")
    assert e.value.status == 400
    state = urllib.parse.parse_qs(urllib.parse.urlparse(sp.login_url()).query)["state"][0]
    clock.now += 601
    with pytest.raises(SpotifyError):
        sp.handle_callback("c", state)
    assert net.calls == []


def test_no_configurado_ni_vinculado(net, clock, tmp_path):
    with pytest.raises(SpotifyError) as e:
        SpotifyClient(None, fetch=net).login_url()
    assert e.value.status == 409
    sp = make(net, clock, tmp_path)
    with pytest.raises(SpotifyError) as e:
        sp.devices()
    assert e.value.status == 409 and not sp.linked


def test_token_vigente_no_refresca(net, clock, tmp_path):
    sp = make(net, clock, tmp_path)
    link(sp, clock)
    sp.devices()
    assert net.calls[0][2]["Authorization"] == "Bearer a1"
    assert net.paths("POST") == []


def test_refresca_antes_de_expirar_y_guarda_refresh_nuevo(net, clock, tmp_path):
    sp = make(net, clock, tmp_path)
    link(sp, clock, expires_in=30)
    net.on("POST", "/api/token", TOKEN_RESP)
    sp.devices()
    form = urllib.parse.parse_qs(net.calls[0][3].decode())
    assert form["grant_type"] == ["refresh_token"] and form["refresh_token"] == ["r1"]
    assert net.calls[1][2]["Authorization"] == "Bearer acc"
    assert json.loads(sp.token_file.read_text())["refresh_token"] == "ref"


def test_refresca_conserva_refresh_si_no_viene_nuevo(net, clock, tmp_path):
    sp = make(net, clock, tmp_path)
    link(sp, clock, expires_in=0)
    net.on("POST", "/api/token", (200, {"access_token": "acc", "expires_in": 3600}))
    sp.devices()
    assert json.loads(sp.token_file.read_text())["refresh_token"] == "r1"


def test_reintenta_en_401(net, clock, tmp_path):
    sp = make(net, clock, tmp_path)
    link(sp, clock)
    net.on(
        "GET",
        "/v1/me/player/devices",
        (401, {"error": {"message": "expired"}}),
        (200, {"devices": [PHONE]}),
    )
    net.on("POST", "/api/token", TOKEN_RESP)
    assert sp.devices() == [PHONE]
    assert net.paths() == ["/v1/me/player/devices", "/api/token", "/v1/me/player/devices"]
    assert net.calls[2][2]["Authorization"] == "Bearer acc"


def test_error_de_api(net, clock, tmp_path):
    sp = make(net, clock, tmp_path)
    link(sp, clock)
    net.on("GET", "/v1/me/player/devices", (403, {"error": {"message": "Premium requerido"}}))
    with pytest.raises(SpotifyError) as e:
        sp.devices()
    assert e.value.status == 403 and "Premium" in e.value.message


def test_search_uri(net, clock, tmp_path):
    sp = make(net, clock, tmp_path)
    link(sp, clock)
    net.on("GET", "/v1/search", (200, {"artists": {"items": [{"uri": "spotify:artist:1"}]}}))
    assert sp.search_uri("Soda Stereo", "artist") == "spotify:artist:1"
    q = urllib.parse.parse_qs(urllib.parse.urlparse(net.calls[0][1]).query)
    assert q["q"] == ["Soda Stereo"] and q["limit"] == ["1"] and q["market"] == ["from_token"]
    net.on("GET", "/v1/search", (200, {"artists": {"items": []}}))
    with pytest.raises(SpotifyError) as e:
        sp.search_uri("nadie", "artist")
    assert e.value.status == 404


def test_find_device(net, clock, tmp_path):
    sp = make(net, clock, tmp_path)
    link(sp, clock)
    assert sp.find_device("sala nandu")["id"] == "dev2"
    assert sp.find_device("REDMI")["id"] == "dev1"
    assert sp.find_device()["id"] == "dev2"  # el activo
    net.devices = [PHONE]
    assert sp.find_device()["id"] == "dev1"  # Smartphone
    with pytest.raises(SpotifyError) as e:
        sp.find_device("cocina")
    assert e.value.status == 404 and "Redmi Note 8" in e.value.message


def put_bodies(net, path):
    return [
        json.loads(c[3]) for c in net.calls if c[0] == "PUT" and c[1].split("?")[0].endswith(path)
    ]


def test_play_artista_usa_context_uri_y_device(net, clock, tmp_path):
    sp = make(net, clock, tmp_path, device="redmi")
    link(sp, clock)
    net.on("GET", "/v1/search", (200, {"artists": {"items": [{"uri": "spotify:artist:1"}]}}))
    out = sp.play(query="x")
    assert out == {"uri": "spotify:artist:1", "device": "Redmi Note 8", "type": "artist"}
    assert put_bodies(net, "/play") == [{"context_uri": "spotify:artist:1"}]
    assert "device_id=dev1" in [c[1] for c in net.calls if c[0] == "PUT"][-1]
    assert net.paths("PUT") == ["/v1/me/player/play"]  # sin shuffle no se toca


def test_play_track_usa_uris_y_shuffle(net, clock, tmp_path):
    sp = make(net, clock, tmp_path)
    link(sp, clock)
    sp.play(uri="spotify:track:9", device="sala", shuffle=True)
    assert net.paths("PUT") == ["/v1/me/player/shuffle", "/v1/me/player/play"]
    shuffle_url = [c[1] for c in net.calls if "shuffle" in c[1]][0]
    assert "state=true" in shuffle_url and "device_id=dev2" in shuffle_url
    assert put_bodies(net, "/play") == [{"uris": ["spotify:track:9"]}]


def test_play_device_ausente_404(net, clock, tmp_path):
    sp = make(net, clock, tmp_path)
    link(sp, clock)
    with pytest.raises(SpotifyError) as e:
        sp.play(uri="spotify:album:1", device="cocina")
    assert e.value.status == 404 and "Sala Ñandú" in e.value.message
    assert net.paths("PUT") == []


# --- Endpoints ---


@pytest.fixture
def api(net, clock, tmp_path):
    sp = make(net, clock, tmp_path)
    app = create_app(devices={"lamp": FakeDevice("lamp", "L")}, token=TOKEN, spotify=sp)
    return TestClient(app, follow_redirects=False), sp


def test_login_token_por_query(api):
    c, _ = api
    assert c.get("/spotify/login").status_code == 401
    assert c.get("/spotify/login?token=mal").status_code == 401
    r = c.get(f"/spotify/login?token={TOKEN}")
    assert r.status_code == 307
    assert r.headers["location"].startswith("https://accounts.spotify.com/authorize?")


def test_login_sin_configurar_409(net):
    app = create_app(devices={}, token=TOKEN, spotify=SpotifyClient(None, fetch=net))
    r = TestClient(app, follow_redirects=False).get(f"/spotify/login?token={TOKEN}")
    assert r.status_code == 409


def test_callback_ok_y_error(api, net):
    c, sp = api
    net.on("POST", "/api/token", TOKEN_RESP)
    loc = c.get(f"/spotify/login?token={TOKEN}").headers["location"]
    state = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)["state"][0]
    r = c.get(f"/spotify/callback?code=C&state={state}")
    assert r.status_code == 200 and "Spotify vinculado. Ya puedes cerrar esta pestaña." in r.text
    assert sp.linked
    r = c.get("/spotify/callback?code=C&state=mal")
    assert r.status_code == 400 and "State inválido" in r.text
    assert c.get("/spotify/callback?error=access_denied").status_code == 400


def test_status(api, net, clock):
    c, sp = api
    assert c.get("/spotify/status").status_code == 401
    assert c.get("/spotify/status", headers=HEADERS).json() == {
        "configured": True,
        "linked": False,
        "devices": None,
    }
    link(sp, clock)
    data = c.get("/spotify/status", headers=HEADERS).json()
    assert data["linked"] and data["devices"][1] == {
        "name": "Sala Ñandú",
        "type": "Speaker",
        "active": True,
    }
    net.on("GET", "/v1/me/player/devices", (500, {"error": {"message": "caído"}}))
    data = c.get("/spotify/status", headers=HEADERS).json()
    assert data["devices"] is None and data["error"] == "caído"


def test_play_endpoint(api, net, clock):
    c, sp = api
    assert c.post("/spotify/play", json={"query": "x"}).status_code == 401
    r = c.post("/spotify/play", json={"query": "x"}, headers=HEADERS)
    assert r.status_code == 409  # no vinculado
    link(sp, clock)
    assert c.post("/spotify/play", json={}, headers=HEADERS).status_code == 422
    r = c.post("/spotify/play", json={"uri": "spotify:track:1", "device": "x"}, headers=HEADERS)
    assert r.status_code == 404 and "Disponibles" in r.json()["detail"]
    r = c.post("/spotify/play", json={"uri": "spotify:track:1"}, headers=HEADERS)
    assert r.status_code == 200 and r.json()["type"] == "track"
    net.on("PUT", "/v1/me/player/play", (500, {"error": {"message": "boom"}}))
    r = c.post("/spotify/play", json={"uri": "spotify:track:1"}, headers=HEADERS)
    assert r.status_code == 502 and r.json()["detail"] == "boom"


# --- Escenas ---


def scene_ctx(sp, sleeps):
    return SceneContext({}, None, {}, CommandQueue(), sleeps.append, sp)


def test_escena_parseo():
    steps = parse_scenes({"s": [{"spotify": {"play": "Soda", "shuffle": True}}]}, [], [])["s"]
    assert steps[0].args == {
        "query": "Soda",
        "uri": None,
        "type": "artist",
        "device": None,
        "shuffle": True,
    }
    for bad in ({}, {"play": "x", "type": "podcast"}, {"play": "x", "shuffle": "si"}):
        with pytest.raises(ValueError):
            parse_scenes({"s": [{"spotify": bad}]}, [], [])


def test_escena_spotify_ok(net, clock, tmp_path):
    sp = make(net, clock, tmp_path)
    link(sp, clock)
    net.on("GET", "/v1/search", (200, {"artists": {"items": [{"uri": "spotify:artist:1"}]}}))
    steps = parse_scenes({"s": [{"spotify": {"play": "x", "device": "redmi"}}]}, [], [])["s"]
    sleeps: list[float] = []
    ctx = scene_ctx(sp, sleeps)
    (res,) = run_scene(steps, ctx)
    assert res["ok"] and "spotify:artist:1" in res["detail"] and sleeps == []


def test_escena_spotify_wake_y_reintento(net, clock, tmp_path):
    sp = make(net, clock, tmp_path)
    link(sp, clock)
    net.on("GET", "/v1/search", (200, {"artists": {"items": [{"uri": "spotify:artist:1"}]}}))
    orig = net.__call__
    state = {"n": 0}

    def flaky(method, url, headers, data):
        if url.endswith("/me/player/devices"):
            state["n"] += 1
            if state["n"] == 1:
                return 200, json.dumps({"devices": []}).encode()
        return orig(method, url, headers, data)

    sp._fetch = flaky
    steps = parse_scenes({"s": [{"spotify": {"play": "x"}}]}, [], [])["s"]
    sleeps: list[float] = []
    ctx = scene_ctx(sp, sleeps)
    (res,) = run_scene(steps, ctx)
    assert res["ok"] and sleeps == [3]
    assert [c.action for c in ctx.queue.after(0)] == ["wake"]


def test_escena_spotify_sin_dispositivo_falla(net, clock, tmp_path):
    sp = make(net, clock, tmp_path)
    link(sp, clock)
    net.devices = []
    steps = parse_scenes({"s": [{"spotify": {"uri": "spotify:track:1"}}]}, [], [])["s"]
    sleeps: list[float] = []
    (res,) = run_scene(steps, scene_ctx(sp, sleeps))
    assert not res["ok"] and "Disponibles" in res["detail"] and sleeps == [3]


def test_escena_sin_cliente():
    steps = parse_scenes({"s": [{"spotify": {"play": "x"}}]}, [], [])["s"]
    (res,) = run_scene(steps, scene_ctx(None, []))
    assert not res["ok"] and "no configurado" in res["detail"]
