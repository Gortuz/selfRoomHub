import base64
import hashlib

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.now_playing import NowPlaying, NowPlayingUpdate

TOKEN = "test-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

JPEG = b"\xff\xd8\xff\xe0" + b"jpeg-data"
PNG = b"\x89PNG\r\n\x1a\n" + b"png-data"
WEBP = b"RIFF\x04\x00\x00\x00WEBP" + b"webp-data"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def song(**extra: object) -> dict[str, object]:
    return {"playing": True, "title": "T", "artist": "A", "album": "L", "app": "x", **extra}


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(devices={}, token=TOKEN))


def test_initial_state(client: TestClient) -> None:
    r = client.get("/now-playing", headers=HEADERS)
    assert r.status_code == 200
    assert r.json() == {
        "playing": False,
        "title": None,
        "artist": None,
        "album": None,
        "app": None,
        "art_url": None,
        "volume": None,
        "position_ms": None,
        "duration_ms": None,
        "updated_at": None,
    }


def test_auth_required(client: TestClient) -> None:
    assert client.get("/now-playing").status_code == 401
    assert client.put("/now-playing", json={"playing": False}).status_code == 401


def test_art_without_auth_404_when_empty(client: TestClient) -> None:
    assert client.get("/now-playing/art").status_code == 404


@pytest.mark.parametrize(
    ("data", "mime"),
    [(JPEG, "image/jpeg"), (PNG, "image/png"), (WEBP, "image/webp")],
)
def test_put_with_art(client: TestClient, data: bytes, mime: str) -> None:
    r = client.put("/now-playing", headers=HEADERS, json=song(art_base64=b64(data)))
    assert r.status_code == 200
    body = r.json()
    v = hashlib.sha1(data).hexdigest()[:8]
    assert body["art_url"] == f"/now-playing/art?v={v}"
    assert body["title"] == "T"
    assert body["updated_at"] is not None
    assert client.get("/now-playing", headers=HEADERS).json() == body
    art = client.get("/now-playing/art")
    assert art.status_code == 200
    assert art.content == data
    assert art.headers["content-type"] == mime
    assert art.headers["cache-control"] == "public, max-age=86400"


def test_invalid_base64(client: TestClient) -> None:
    r = client.put("/now-playing", headers=HEADERS, json=song(art_base64="@@no-b64@@"))
    assert r.status_code == 422


def test_too_large(client: TestClient) -> None:
    big = JPEG + b"0" * (2 * 1024 * 1024)
    r = client.put("/now-playing", headers=HEADERS, json=song(art_base64=b64(big)))
    assert r.status_code == 422


def test_unknown_type(client: TestClient) -> None:
    r = client.put("/now-playing", headers=HEADERS, json=song(art_base64=b64(b"GIF89a....")))
    assert r.status_code == 422


def test_art_kept_for_same_song(client: TestClient) -> None:
    first = client.put("/now-playing", headers=HEADERS, json=song(art_base64=b64(JPEG))).json()
    second = client.put("/now-playing", headers=HEADERS, json=song()).json()
    assert second["art_url"] == first["art_url"]
    assert client.get("/now-playing/art").content == JPEG


def test_art_dropped_when_song_changes(client: TestClient) -> None:
    client.put("/now-playing", headers=HEADERS, json=song(art_base64=b64(JPEG)))
    r = client.put("/now-playing", headers=HEADERS, json=song(title="Otra"))
    assert r.json()["art_url"] is None
    assert client.get("/now-playing/art").status_code == 404


def test_stop_clears_everything(client: TestClient) -> None:
    client.put("/now-playing", headers=HEADERS, json=song(art_base64=b64(JPEG)))
    r = client.put("/now-playing", headers=HEADERS, json={"playing": False})
    body = r.json()
    assert body["playing"] is False
    assert body["title"] is None
    assert body["art_url"] is None
    assert body["updated_at"] is not None
    assert client.get("/now-playing/art").status_code == 404


def test_v_changes_with_image(client: TestClient) -> None:
    a = client.put("/now-playing", headers=HEADERS, json=song(art_base64=b64(JPEG))).json()
    b = client.put("/now-playing", headers=HEADERS, json=song(art_base64=b64(PNG))).json()
    assert a["art_url"] != b["art_url"]


def test_state_is_per_app(client: TestClient) -> None:
    client.put("/now-playing", headers=HEADERS, json=song())
    other = TestClient(create_app(devices={}, token=TOKEN))
    assert other.get("/now-playing", headers=HEADERS).json()["playing"] is False


def test_panel_serves_index(client: TestClient) -> None:
    r = client.get("/panel/")
    assert r.status_code == 200
    assert "html" in r.headers["content-type"]


def test_panel_redirects(client: TestClient) -> None:
    r = client.get("/panel", follow_redirects=False)
    assert r.status_code in (307, 308)
    assert r.headers["location"].endswith("/panel/")


def test_panel_no_queda_en_cache(client):
    # El kiosco debe ver los cambios del panel sin borrar la caché del WebView
    r = client.get("/panel/")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-cache"


def test_volume_saved_kept_and_not_cleared(client: TestClient) -> None:
    r = client.put("/now-playing", headers=HEADERS, json=song(volume=40))
    assert r.json()["volume"] == 40
    # Sin volumen en el PUT se conserva
    assert client.put("/now-playing", headers=HEADERS, json=song()).json()["volume"] == 40
    # playing false no lo borra
    r = client.put("/now-playing", headers=HEADERS, json={"playing": False})
    assert r.json()["volume"] == 40
    assert client.get("/now-playing", headers=HEADERS).json()["volume"] == 40
    r = client.put("/now-playing", headers=HEADERS, json={"playing": False, "volume": 0})
    assert r.json()["volume"] == 0


def test_volume_out_of_range(client: TestClient) -> None:
    r = client.put("/now-playing", headers=HEADERS, json=song(volume=101))
    assert r.status_code == 422


# --- posición de reproducción ---


class Clock:
    def __init__(self, now: int) -> None:
        self.now = now

    def __call__(self) -> int:
        return self.now


def make_np() -> tuple[NowPlaying, Clock]:
    clock = Clock(1_000_000)
    return NowPlaying(clock=clock), clock


def put(np: NowPlaying, **fields: object) -> None:
    np.update(NowPlayingUpdate(**{"playing": True, "title": "T", "artist": "A", **fields}))


def test_position_null_by_default() -> None:
    np, _ = make_np()
    put(np)
    assert np.to_json()["position_ms"] is None
    assert np.to_json()["duration_ms"] is None


def test_position_extrapolated_while_playing() -> None:
    np, clock = make_np()
    put(np, position_ms=10_000, duration_ms=200_000, position_at=1_000_000)
    clock.now += 5_000
    j = np.to_json()
    assert j["position_ms"] == 15_000
    assert j["duration_ms"] == 200_000
    assert "position_at" not in j and "speed" not in j


def test_position_uses_speed() -> None:
    np, clock = make_np()
    put(np, position_ms=0, position_at=1_000_000, speed=2.0)
    clock.now += 3_000
    assert np.to_json()["position_ms"] == 6_000


def test_position_not_extrapolated_when_paused() -> None:
    np, clock = make_np()
    np.update(NowPlayingUpdate(playing=False, position_ms=7_000, position_at=1_000_000))
    clock.now += 5_000
    assert np.to_json()["position_ms"] == 7_000


def test_position_without_position_at_is_not_extrapolated() -> None:
    np, clock = make_np()
    put(np, position_ms=4_000)
    clock.now += 9_000
    assert np.to_json()["position_ms"] == 4_000


def test_position_capped_to_duration() -> None:
    np, clock = make_np()
    put(np, position_ms=9_000, duration_ms=10_000, position_at=1_000_000)
    clock.now += 60_000
    assert np.to_json()["position_ms"] == 10_000


def test_position_never_negative() -> None:
    np, _ = make_np()
    put(np, position_ms=1_000, position_at=1_005_000)  # medida "en el futuro"
    assert np.to_json()["position_ms"] == 0


def test_same_song_keeps_missing_position_fields() -> None:
    np, _ = make_np()
    put(np, position_ms=1_000, duration_ms=200_000, position_at=1_000_000, speed=1.5)
    put(np, position_ms=2_000, position_at=1_001_000)
    assert np.duration_ms == 200_000
    assert np.speed == 1.5
    assert np.position_ms == 2_000


def test_new_song_resets_missing_position_fields() -> None:
    np, _ = make_np()
    put(np, position_ms=1_000, duration_ms=200_000, position_at=1_000_000, speed=1.5)
    put(np, title="Otra", position_ms=500, position_at=1_000_000)
    assert np.duration_ms is None
    assert np.speed == 1.0
    assert np.position_ms == 500
    put(np, title="Tercera")
    j = np.to_json()
    assert j["position_ms"] is None and j["duration_ms"] is None


def test_position_through_api(client: TestClient) -> None:
    r = client.put("/now-playing", headers=HEADERS, json=song(position_ms=5, duration_ms=10))
    assert r.json()["duration_ms"] == 10
    assert client.put("/now-playing", headers=HEADERS, json=song(position_ms=-1)).status_code == 422
