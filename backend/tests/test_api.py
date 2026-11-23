from tests.conftest import HEADERS


def test_health_sin_auth(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_auth(client):
    assert client.get("/devices").status_code == 401
    assert client.get("/devices", headers={"Authorization": "Bearer mal"}).status_code == 401
    assert client.get("/devices", headers=HEADERS).status_code == 200


def test_lista_y_detalle(client):
    data = client.get("/devices", headers=HEADERS).json()
    assert {"id": "lamp", "name": "Lámpara", "online": True, "on": False} in data
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
