import base64
import json
import re
import urllib.error

import pytest
from fastapi.testclient import TestClient

from app.battery import BatteryMonitor
from app.battery_alerts import (
    Alert,
    BatteryWatcher,
    NtfyNotifier,
    Thresholds,
    advice,
    notifier_from_env,
    thresholds_from_env,
)
from app.main import create_app

TOKEN = "test-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
T = Thresholds()


def bat(pct, charging=False):
    return {"percentage": pct, "charging": charging}


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Sink:
    def __init__(self, ok=True):
        self.sent: list[Alert] = []
        self.ok = ok

    def send(self, alert):
        self.sent.append(alert)
        return self.ok


def watcher(**kw):
    clock = Clock()
    return BatteryWatcher(T, Sink(), clock, **kw), clock


def kinds(alerts):
    return [a.kind for a in alerts]


# --- advice ---


@pytest.mark.parametrize(
    ("pct", "charging", "expected"),
    [
        (15, False, "critical"),
        (10, False, "critical"),
        (16, False, "connect"),
        (25, False, "connect"),
        (26, False, None),
        (15, True, None),
        (25, True, None),
        (79, True, None),
        (80, True, "disconnect"),
        (100, True, "disconnect"),
        (90, False, None),
    ],
)
def test_advice(pct, charging, expected):
    assert advice(bat(pct, charging), T) == expected


# --- máquina de estados ---


def test_primer_evaluate_en_zona_avisa():
    w, _ = watcher()
    alerts = w.evaluate(bat(20))
    assert kinds(alerts) == ["connect"]
    assert alerts[0].title == "Conecta el cargador"
    assert alerts[0].message == "La batería del servidor está al 20 %."


def test_connect_un_solo_aviso_por_cruce():
    w, _ = watcher()
    assert kinds(w.evaluate(bat(25))) == ["connect"]
    assert w.evaluate(bat(24)) == []
    assert w.evaluate(bat(22)) == []


def test_connect_se_rearma_al_cargar():
    w, _ = watcher()
    w.evaluate(bat(22))
    w.evaluate(bat(22, True))
    assert kinds(w.evaluate(bat(22))) == ["connect"]


def test_connect_se_rearma_sobre_low_mas_5():
    w, _ = watcher()
    w.evaluate(bat(22))
    assert w.evaluate(bat(28)) == []  # histéresis: aún no se rearma
    assert w.evaluate(bat(24)) == []
    w.evaluate(bat(31))
    assert kinds(w.evaluate(bat(25))) == ["connect"]


def test_disconnect_y_rearme():
    w, _ = watcher()
    alerts = w.evaluate(bat(80, True))
    assert kinds(alerts) == ["disconnect"]
    assert alerts[0].title == "Ya puedes desconectar el cargador"
    assert alerts[0].message == (
        "La batería llegó al 80 %. Mantenerla entre 25 y 80 % alarga su vida."
    )
    assert w.evaluate(bat(85, True)) == []
    assert w.evaluate(bat(77, True)) == []  # sigue sin rearmar (>= high-5)
    assert w.evaluate(bat(80, True)) == []
    w.evaluate(bat(74, True))
    assert kinds(w.evaluate(bat(80, True))) == ["disconnect"]


def test_disconnect_se_rearma_al_desconectar():
    w, _ = watcher()
    w.evaluate(bat(82, True))
    w.evaluate(bat(82, False))
    assert kinds(w.evaluate(bat(82, True))) == ["disconnect"]


def test_critical_repite_cada_15_min():
    w, clock = watcher()
    first = w.evaluate(bat(12))
    assert kinds(first) == ["critical"]  # sin connect en el mismo cruce
    a = first[0]
    assert a.priority == "urgent"
    assert a.title == "Batería crítica"
    assert a.message == ("Queda 12 % y no está cargando. Si se apaga, el cuarto deja de responder.")
    clock.now = 60
    assert w.evaluate(bat(12)) == []
    clock.now = 899
    assert w.evaluate(bat(11)) == []
    clock.now = 900
    assert kinds(w.evaluate(bat(11))) == ["critical"]
    clock.now = 1799
    assert w.evaluate(bat(10)) == []
    clock.now = 1800
    assert kinds(w.evaluate(bat(10))) == ["critical"]


def test_critical_intervalo_configurable():
    w, clock = watcher(critical_every=10)
    w.evaluate(bat(10))
    clock.now = 10
    assert kinds(w.evaluate(bat(10))) == ["critical"]


def test_critical_no_manda_connect_despues():
    w, _ = watcher()
    w.evaluate(bat(14))
    assert w.evaluate(bat(18)) == []  # sale de critical pero sigue en connect ya avisado


def test_de_connect_a_critical_avisa_critical():
    w, _ = watcher()
    assert kinds(w.evaluate(bat(20))) == ["connect"]
    assert kinds(w.evaluate(bat(15))) == ["critical"]


def test_critical_rearma_al_cargar():
    w, clock = watcher()
    w.evaluate(bat(12))
    w.evaluate(bat(13, True))
    clock.now = 5
    assert kinds(w.evaluate(bat(12))) == ["critical"]


def test_prioridades_y_tags():
    w, _ = watcher()
    connect = w.evaluate(bat(20))[0]
    assert connect.priority == "high"
    disc = BatteryWatcher(T, Sink(), Clock()).evaluate(bat(80, True))[0]
    assert disc.priority == "default"
    assert connect.tags and disc.tags


def test_textos_usan_umbrales_reales():
    t = Thresholds(low=30, high=90, critical=10)
    w = BatteryWatcher(t, Sink(), Clock())
    assert "entre 30 y 90 %" in w.evaluate(bat(90, True))[0].message


# --- notificador ntfy ---


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_opener(calls, error=None):
    def opener(req, timeout=None):
        calls.append((req, timeout))
        if error:
            raise error
        return FakeResponse()

    return opener


ALERT = Alert("connect", "Conecta el cargador", "Batería al 22 %.", "high", ["battery", "warning"])


def test_ntfy_envia_post():
    calls = []
    n = NtfyNotifier("https://ntfy.example/", "tema", opener=fake_opener(calls))
    assert n.send(ALERT) is True
    req, timeout = calls[0]
    assert req.full_url == "https://ntfy.example/tema"
    assert req.get_method() == "POST"
    assert req.data == "Batería al 22 %.".encode()
    assert timeout == 10
    h = {k.lower(): v for k, v in req.header_items()}
    m = re.fullmatch(r"=\?UTF-8\?B\?(.+)\?=", h["title"])
    assert m and base64.b64decode(m.group(1)).decode() == "Conecta el cargador"
    assert h["priority"] == "high"
    assert h["tags"] == "battery,warning"
    assert "authorization" not in h


def test_ntfy_con_token():
    calls = []
    NtfyNotifier("https://x", "t", token="tk_1", opener=fake_opener(calls)).send(ALERT)
    h = {k.lower(): v for k, v in calls[0][0].header_items()}
    assert h["authorization"] == "Bearer tk_1"


def test_ntfy_error_de_red_no_lanza(caplog):
    calls = []
    n = NtfyNotifier("https://x", "t", opener=fake_opener(calls, urllib.error.URLError("caído")))
    assert n.send(ALERT) is False
    assert "ntfy" in caplog.text.lower()
    n = NtfyNotifier("https://x", "t", opener=fake_opener(calls, TimeoutError()))
    assert n.send(ALERT) is False


# --- entorno ---


def test_notifier_desactivado_sin_topic():
    assert notifier_from_env({}) is None
    assert notifier_from_env({"SELFROOMHUB_NTFY_TOPIC": "  "}) is None


def test_notifier_desde_env():
    n = notifier_from_env({"SELFROOMHUB_NTFY_TOPIC": "abc", "SELFROOMHUB_NTFY_TOKEN": "tk"})
    assert isinstance(n, NtfyNotifier)
    assert n.url == "https://ntfy.sh"
    assert n.topic == "abc"
    assert n.token == "tk"
    n = notifier_from_env({"SELFROOMHUB_NTFY_TOPIC": "abc", "SELFROOMHUB_NTFY_URL": "http://h:1"})
    assert n.url == "http://h:1"
    assert n.token is None


def test_umbrales_por_defecto_y_env():
    assert thresholds_from_env({}) == Thresholds(low=25, high=80, critical=15)
    env = {
        "SELFROOMHUB_BATTERY_LOW": "30",
        "SELFROOMHUB_BATTERY_HIGH": "90",
        "SELFROOMHUB_BATTERY_CRITICAL": "10",
    }
    assert thresholds_from_env(env) == Thresholds(low=30, high=90, critical=10)


def test_umbrales_invalidos():
    with pytest.raises(ValueError, match="SELFROOMHUB_BATTERY_LOW"):
        thresholds_from_env({"SELFROOMHUB_BATTERY_LOW": "mucho"})
    with pytest.raises(ValueError, match="critical"):
        thresholds_from_env({"SELFROOMHUB_BATTERY_CRITICAL": "40"})


# --- endpoints ---


def make_client(notifier=None, percentage=20, charging=False):
    status = "CHARGING" if charging else "DISCHARGING"
    payload = json.dumps({"percentage": percentage, "status": status})

    def run(cmd, **kw):
        import subprocess

        return subprocess.CompletedProcess(cmd, 0, stdout=payload, stderr="")

    app = create_app(devices={}, token=TOKEN, battery=BatteryMonitor(runner=run), notifier=notifier)
    return TestClient(app)


def test_battery_incluye_advice():
    body = make_client().get("/battery", headers=HEADERS).json()
    assert body["advice"] == "connect"
    assert make_client(percentage=50).get("/battery", headers=HEADERS).json()["advice"] is None


def test_test_alert_requiere_auth():
    assert make_client(Sink()).post("/battery/test-alert").status_code == 401


def test_test_alert_409_sin_notifier():
    r = make_client().post("/battery/test-alert", headers=HEADERS)
    assert r.status_code == 409
    assert r.json() == {"detail": "Avisos externos desactivados: falta SELFROOMHUB_NTFY_TOPIC"}


def test_test_alert_200():
    sink = Sink()
    r = make_client(sink).post("/battery/test-alert", headers=HEADERS)
    assert r.status_code == 200
    assert sink.sent[0].title == "Prueba de avisos"
    assert sink.sent[0].message == "Si ves esto, los avisos de batería funcionan."


def test_test_alert_502_si_falla():
    r = make_client(Sink(ok=False)).post("/battery/test-alert", headers=HEADERS)
    assert r.status_code == 502
