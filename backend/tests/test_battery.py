import json
import subprocess

from fastapi.testclient import TestClient

from app.battery import BatteryError, BatteryMonitor
from app.main import create_app

TOKEN = "test-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
SAMPLE = {
    "health": "GOOD",
    "percentage": 87,
    "plugged": "PLUGGED_AC",
    "status": "CHARGING",
    "temperature": 30.1,
}


def runner(payload=SAMPLE, returncode=0, calls=None):
    def run(cmd, **kwargs):
        if calls is not None:
            calls.append(cmd)
        out = payload if isinstance(payload, str) else json.dumps(payload)
        return subprocess.CompletedProcess(cmd, returncode, stdout=out, stderr="")

    return run


def test_lee_estado():
    b = BatteryMonitor(runner=runner()).read()
    assert b == {"percentage": 87, "charging": True, "status": "CHARGING", "temperature": 30.1}


def test_descargando_no_es_carga():
    b = BatteryMonitor(
        runner=runner({**SAMPLE, "status": "DISCHARGING", "plugged": "UNPLUGGED"})
    ).read()
    assert b["charging"] is False


def test_lleno_y_enchufado_cuenta_como_carga():
    b = BatteryMonitor(runner=runner({**SAMPLE, "status": "FULL"})).read()
    assert b["charging"] is True


def test_cachea_la_lectura():
    calls, now = [], [0.0]
    m = BatteryMonitor(runner=runner(calls=calls), clock=lambda: now[0], ttl=60)
    m.read()
    now[0] = 30
    m.read()
    assert len(calls) == 1
    now[0] = 61
    m.read()
    assert len(calls) == 2


def test_errores():
    for bad in (runner(returncode=1), runner(payload="no es json"), runner(payload={"x": 1})):
        try:
            BatteryMonitor(runner=bad).read()
        except BatteryError:
            continue
        raise AssertionError("debía fallar")


def test_comando_inexistente():
    def missing(cmd, **kwargs):
        raise FileNotFoundError

    try:
        BatteryMonitor(runner=missing).read()
    except BatteryError:
        return
    raise AssertionError("debía fallar")


def test_endpoint():
    client = TestClient(
        create_app(devices={}, token=TOKEN, battery=BatteryMonitor(runner=runner()))
    )
    assert client.get("/battery").status_code == 401
    assert client.get("/battery", headers=HEADERS).json()["percentage"] == 87


def test_endpoint_sin_bateria_503():
    client = TestClient(
        create_app(devices={}, token=TOKEN, battery=BatteryMonitor(runner=runner(returncode=1)))
    )
    assert client.get("/battery", headers=HEADERS).status_code == 503
