from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.devices.fake import FakeDevice
from app.main import create_app
from app.mode import ModeState
from tests.conftest import HEADERS, TOKEN


class Clock:
    def __init__(self, hhmm: str, day: int = 10) -> None:
        h, m = hhmm.split(":")
        self.now = datetime(2026, 1, day, int(h), int(m))

    def __call__(self) -> datetime:
        return self.now


@pytest.mark.parametrize(
    "hhmm,expected",
    [
        ("22:59", "day"),
        ("23:00", "night"),
        ("00:00", "night"),
        ("05:59", "night"),
        ("06:00", "day"),
        ("12:00", "day"),
    ],
)
def test_horario_cruza_medianoche(hhmm, expected):
    state = ModeState(clock=Clock(hhmm))
    assert state.current() == {"mode": expected, "source": "schedule"}


def test_horario_sin_cruzar():
    s = ModeState("01:00", "05:00", Clock("03:00"))
    assert s.schedule_mode(s._clock()) == "night"
    assert s.schedule_mode(datetime(2026, 1, 1, 5, 0)) == "day"


def test_forzado_dura_hasta_el_proximo_limite():
    clock = Clock("20:00")
    s = ModeState(clock=clock)
    s.set("night")
    assert s.current() == {"mode": "night", "source": "scene"}
    clock.now = datetime(2026, 1, 10, 22, 59)
    assert s.current()["source"] == "scene"
    clock.now = datetime(2026, 1, 10, 23, 0)  # límite: vuelve al horario
    assert s.current() == {"mode": "night", "source": "schedule"}


def test_forzado_dia_de_madrugada_expira_a_las_06():
    clock = Clock("02:00")
    s = ModeState(clock=clock)
    s.set("day")
    assert s.current() == {"mode": "day", "source": "scene"}
    clock.now += timedelta(hours=4)
    assert s.current() == {"mode": "day", "source": "schedule"}


def test_forzado_cruza_al_dia_siguiente():
    clock = Clock("23:30")
    s = ModeState(clock=clock)
    s.set("day")
    clock.now = datetime(2026, 1, 11, 5, 59)
    assert s.current() == {"mode": "day", "source": "scene"}
    clock.now = datetime(2026, 1, 11, 6, 0)
    assert s.current() == {"mode": "day", "source": "schedule"}


def test_auto_limpia():
    s = ModeState(clock=Clock("12:00"))
    s.set("night")
    s.set("auto")
    assert s.current() == {"mode": "day", "source": "schedule"}


def test_modo_invalido():
    with pytest.raises(ValueError):
        ModeState(clock=Clock("12:00")).set("x")


@pytest.mark.parametrize("bad", ["25:00", "6:00", "06:60", "abc", ""])
def test_hora_invalida(bad):
    with pytest.raises(ValueError):
        ModeState(night_from=bad)


def test_horas_iguales_invalidas():
    with pytest.raises(ValueError):
        ModeState("06:00", "06:00")


def test_env(monkeypatch):
    monkeypatch.setenv("SELFROOMHUB_NIGHT_FROM", "21:00")
    monkeypatch.setenv("SELFROOMHUB_NIGHT_TO", "07:00")
    s = ModeState.from_env(Clock("21:30"))
    assert s.current()["mode"] == "night"
    monkeypatch.setenv("SELFROOMHUB_NIGHT_FROM", "mal")
    with pytest.raises(ValueError):
        ModeState.from_env()


def test_endpoints():
    clock = Clock("12:00")
    c = TestClient(create_app(devices={}, token=TOKEN, clock=clock))
    assert c.get("/mode").status_code == 401
    assert c.get("/mode", headers=HEADERS).json() == {"mode": "day", "source": "schedule"}
    r = c.put("/mode", json={"mode": "night"}, headers=HEADERS)
    assert r.json() == {"mode": "night", "source": "scene"}
    assert c.put("/mode", json={"mode": "x"}, headers=HEADERS).status_code == 422
    r = c.put("/mode", json={"mode": "auto"}, headers=HEADERS)
    assert r.json() == {"mode": "day", "source": "schedule"}


def test_timer_endpoint(client):
    r = client.post("/devices/lamp/timer", json={"minutes": 45}, headers=HEADERS)
    assert r.status_code == 200 and r.json() == {"id": "lamp", "minutes": 45}
    assert (
        client.post("/devices/lamp/timer", json={"minutes": 0}, headers=HEADERS).status_code == 200
    )
    for bad in (-1, 721):
        r = client.post("/devices/lamp/timer", json={"minutes": bad}, headers=HEADERS)
        assert r.status_code == 422
    assert client.post("/devices/lamp/timer", json={"minutes": 1}).status_code == 401
    assert (
        client.post("/devices/nada/timer", json={"minutes": 1}, headers=HEADERS).status_code == 404
    )
    r = client.post("/devices/dead/timer", json={"minutes": 1}, headers=HEADERS)
    assert r.status_code == 503


def test_timer_501():
    from app.devices.base import Device, DeviceStatus

    class Plain(Device):
        id, name = "p", "P"

        def on(self) -> None: ...
        def off(self) -> None: ...
        def status(self) -> DeviceStatus:
            return DeviceStatus(True, False)

    c = TestClient(create_app(devices={"p": Plain()}, token=TOKEN))
    assert c.post("/devices/p/timer", json={"minutes": 5}, headers=HEADERS).status_code == 501


def test_fake_guarda_segundos():
    d = FakeDevice("x", "X")
    d.set_timer(120)
    assert d.timer == 120
