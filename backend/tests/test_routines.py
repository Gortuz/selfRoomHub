from datetime import datetime, time

import pytest
from fastapi.testclient import TestClient

from app import config
from app.devices.fake import FakeDevice
from app.main import create_app
from app.routines import parse_routines
from app.scenes import SceneError, parse_scenes
from tests.conftest import HEADERS, TOKEN

RAW = {
    "cama": [
        {"from": "22:00", "to": "06:30", "scene": "noche"},
        {"from": "06:30", "to": "22:00", "scene": "dia"},
    ],
    "solo_tarde": [{"from": "14:00", "to": "18:00", "scene": "dia"}],
}
SCENES = ["noche", "dia"]


def test_ventanas_y_bordes():
    w = parse_routines(RAW, SCENES)["cama"]
    assert [x.scene for x in w if x.contains(time(23, 0))] == ["noche"]
    assert w[0].contains(time(22, 0)) and not w[1].contains(time(22, 0))  # from inclusivo
    assert w[0].contains(time(0, 0)) and w[0].contains(time(6, 29))
    assert not w[0].contains(time(6, 30)) and w[1].contains(time(6, 30))  # to exclusivo
    assert not w[0].contains(time(12, 0))


@pytest.mark.parametrize(
    "raw",
    [
        {"cama": [{"from": "10:00", "to": "10:00", "scene": "dia"}]},
        {"cama": [{"from": "25:00", "to": "10:00", "scene": "dia"}]},
        {"cama": [{"from": "10:00", "to": "11:00", "scene": "nada"}]},
        {"cama": [{"from": "10:00", "scene": "dia"}]},
        {"cama": ["x"]},
        {"cama": {}},
        {"Mala": []},
        [],
    ],
)
def test_invalidas(raw):
    with pytest.raises(SceneError):
        parse_routines(raw, SCENES)


def test_vacia():
    assert parse_routines(None, SCENES) == {}


def test_carga_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv("ESC", "dia")
    f = tmp_path / "d.yaml"
    f.write_text('routines:\n  r:\n    - { from: "08:00", to: "09:00", scene: "${ESC}" }\n')
    assert config.load_routines(f, ["dia"])["r"][0].scene == "dia"
    f.write_text('routines:\n  r:\n    - { from: "08:00", to: "09:00", scene: otra }\n')
    with pytest.raises(SceneError):
        config.load_routines(f, ["dia"])
    assert config.load_routines(tmp_path / "no.yaml", []) == {}


def make_client(hhmm: str) -> tuple[TestClient, FakeDevice]:
    h, m = hhmm.split(":")
    lamp = FakeDevice("lamp", "Lámpara")
    scenes = parse_scenes(
        {
            "noche": [{"mode": "night"}, {"power": {"device": "lamp", "on": True}}],
            "dia": [{"power": {"device": "lamp", "on": False}}],
        },
        ["lamp"],
        [],
    )
    app = create_app(
        devices={"lamp": lamp},
        token=TOKEN,
        scenes=scenes,
        routines=parse_routines(RAW, scenes),
        clock=lambda: datetime(2026, 1, 10, int(h), int(m)),
    )
    return TestClient(app), lamp


def test_ejecuta_ventana_que_cruza_medianoche():
    c, lamp = make_client("01:00")
    r = c.post("/routines/cama", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["routine"] == "cama" and body["scene"] == "noche" and body["ok"] is True
    assert body["name"] == "noche" and len(body["steps"]) == 2
    assert lamp.status().on is True
    assert c.get("/mode", headers=HEADERS).json()["mode"] == "night"


def test_ejecuta_ventana_normal():
    c, lamp = make_client("10:00")
    assert c.post("/routines/cama", headers=HEADERS).json()["scene"] == "dia"


def test_404_409_y_auth():
    c, _ = make_client("10:00")
    assert c.post("/routines/cama").status_code == 401
    assert c.post("/routines/nada", headers=HEADERS).status_code == 404
    r = c.post("/routines/solo_tarde", headers=HEADERS)
    assert r.status_code == 409 and r.json() == {"detail": "Ninguna escena aplica a las 10:00"}


def test_listar():
    c, _ = make_client("10:00")
    data = c.get("/routines", headers=HEADERS).json()
    assert data[0] == {
        "name": "cama",
        "windows": [
            {"from": "22:00", "to": "06:30", "scene": "noche"},
            {"from": "06:30", "to": "22:00", "scene": "dia"},
        ],
    }
