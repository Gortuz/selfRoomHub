import pytest
from fastapi.testclient import TestClient

from app.devices.fake import FakeDevice
from app.main import create_app
from tests.conftest import HEADERS, TOKEN


def test_health_sin_auth(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_auth(client):
    assert client.get("/devices").status_code == 401
    assert client.get("/devices", headers={"Authorization": "Bearer mal"}).status_code == 401
    assert client.get("/devices", headers=HEADERS).status_code == 200


def test_lista_y_detalle(client):
    data = client.get("/devices", headers=HEADERS).json()
    assert {
        "id": "lamp",
        "name": "Lámpara",
        "online": True,
        "on": False,
        "timer": None,
        "light": None,
    } in data
    one = client.get("/devices/lamp", headers=HEADERS).json()
    assert one["id"] == "lamp"


def test_404(client):
    assert client.get("/devices/nada", headers=HEADERS).status_code == 404
    r = client.post("/devices/nada/power", json={"on": True}, headers=HEADERS)
    assert r.status_code == 404


def test_power(client):
    r = client.post("/devices/lamp/power", json={"on": True}, headers=HEADERS)
    assert r.status_code == 200 and r.json()["on"] is True
    r = client.post("/devices/lamp/power", json={"on": False}, headers=HEADERS)
    assert r.json()["on"] is False


def test_power_offline_503(client):
    r = client.post("/devices/dead/power", json={"on": True}, headers=HEADERS)
    assert r.status_code == 503
    assert "dead" in r.json()["detail"]


def test_power_requiere_auth(client):
    assert client.post("/devices/lamp/power", json={"on": True}).status_code == 401


def test_toggle(client):
    r = client.post("/devices/lamp/toggle", headers=HEADERS)
    assert r.status_code == 200 and r.json()["on"] is True
    r = client.post("/devices/lamp/toggle", headers=HEADERS)
    assert r.json()["on"] is False


def test_toggle_offline_503(client):
    assert client.post("/devices/dead/toggle", headers=HEADERS).status_code == 503


def test_toggle_404_y_auth(client):
    assert client.post("/devices/nada/toggle", headers=HEADERS).status_code == 404
    assert client.post("/devices/lamp/toggle").status_code == 401


def test_log_de_acceso_tacha_secretos():
    import logging

    from app.main import RedactSecrets

    rec = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d', None, None
    )
    rec.args = ("127.0.0.1:1", "GET", "/spotify/login?token=abc123&x=1", "1.1", 307)
    RedactSecrets().filter(rec)
    assert "abc123" not in rec.getMessage() and "token=***" in rec.getMessage()
    rec.args = ("127.0.0.1:1", "GET", "/spotify/callback?code=SECRETO&state=s1", "1.1", 200)
    RedactSecrets().filter(rec)
    assert "SECRETO" not in rec.getMessage() and "s1" not in rec.getMessage()


def test_devices_incluye_temporizador(client):
    r = client.get("/devices/lamp", headers=HEADERS).json()
    assert "timer" in r and r["timer"] is None


# --- luz


@pytest.fixture
def light_client() -> TestClient:
    devices = {
        "foco": FakeDevice("foco", "Foco", light=True),
        "lamp": FakeDevice("lamp", "Lámpara"),
        "dead": FakeDevice("dead", "Caído", online=False, light=True),
    }
    return TestClient(create_app(devices=devices, token=TOKEN))


def test_estado_incluye_luz(light_client):
    data = light_client.get("/devices/foco", headers=HEADERS).json()
    assert data["light"]["color_temp_range"] == [2500, 6500]
    assert data["light"]["color"] is True
    assert light_client.get("/devices/lamp", headers=HEADERS).json()["light"] is None


def test_light_temperatura_enciende(light_client):
    r = light_client.post(
        "/devices/foco/light", json={"brightness": 30, "color_temp": 2700}, headers=HEADERS
    )
    assert r.status_code == 200
    body = r.json()
    assert body["on"] is True
    assert (body["light"]["brightness"], body["light"]["color_temp"]) == (30, 2700)


def test_light_color(light_client):
    r = light_client.post(
        "/devices/foco/light", json={"hue": 120, "saturation": 80}, headers=HEADERS
    )
    light = r.json()["light"]
    assert (light["hue"], light["saturation"], light["color_temp"]) == (120, 80, None)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"brightness": 0},
        {"brightness": 101},
        {"hue": 10},
        {"hue": 10, "saturation": 10, "color_temp": 3000},
        {"hue": 361, "saturation": 10},
        {"color_temp": 9000},  # fuera del rango del foco
        {"brillo": 5},
    ],
)
def test_light_invalido(light_client, body):
    r = light_client.post("/devices/foco/light", json=body, headers=HEADERS)
    assert r.status_code == 422


def test_light_sin_soporte_501(light_client):
    r = light_client.post("/devices/lamp/light", json={"brightness": 5}, headers=HEADERS)
    assert r.status_code == 501


def test_light_offline_503(light_client):
    r = light_client.post("/devices/dead/light", json={"brightness": 5}, headers=HEADERS)
    assert r.status_code == 503


def test_light_requiere_auth(light_client):
    assert light_client.post("/devices/foco/light", json={"brightness": 5}).status_code == 401
