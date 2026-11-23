import base64
import hashlib

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

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
