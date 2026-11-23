import subprocess

import pytest
from fastapi.testclient import TestClient

from app import config
from app.bluetooth import BluetoothController, BluetoothError, BluetoothTarget
from app.devices.fake import FakeDevice
from app.main import create_app

ADDR = "AA:BB:CC:DD:EE:FF"
TOKEN = "test-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def runner_returning(stdout="", returncode=0, calls=None):
    def run(cmd, **kwargs):
        if calls is not None:
            calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")

    return run


def make(stdout, **kw):
    return BluetoothController(
        runner=runner_returning(stdout, **kw), rish="/x/rish", dex="/x/b.dex"
    )


def test_connect_ok():
    make("connect 0\n").connect(ADDR.lower())


def test_connect_codigo_distinto_de_cero():
    with pytest.raises(BluetoothError, match="3"):
        make("connect 3").connect(ADDR)


def test_disconnect_ok():
    make("disconnect 0").disconnect(ADDR)


def test_status():
    assert make("status true").is_connected(ADDR) is True
    assert make("status false").is_connected(ADDR) is False


def test_salida_inesperada():
    with pytest.raises(BluetoothError):
        make("").is_connected(ADDR)
    with pytest.raises(BluetoothError):
        make("disconnect 0").connect(ADDR)
    with pytest.raises(BluetoothError):
        make("status maybe").is_connected(ADDR)


def test_returncode_distinto_de_cero():
    with pytest.raises(BluetoothError):
        make("status true", returncode=1).is_connected(ADDR)


@pytest.mark.parametrize("bad", ["AA:BB; rm -rf", "AA:BB:CC:DD:EE", f"{ADDR}; ls", "$(id)"])
def test_direccion_invalida_no_ejecuta(bad):
    calls = []
    ctl = BluetoothController(runner=runner_returning("status true", calls=calls))
    with pytest.raises(BluetoothError):
        ctl.connect(bad)
    assert calls == []


def test_comando_usa_rish_y_direccion_en_mayusculas():
    calls = []
    ctl = BluetoothController(
        runner=runner_returning("status true", calls=calls), rish="/x/rish", dex="/x/b.dex"
    )
    ctl.is_connected(ADDR.lower())
    cmd, kwargs = calls[0]
    assert cmd[:2] == ["env", "-u"] or cmd[0] == "env"
    assert "/x/rish" in cmd
    assert cmd[-1].endswith(f"BtCtl status {ADDR}")
    assert "CLASSPATH=/x/b.dex" in cmd[-1]
    assert kwargs["timeout"] == 15
    assert not kwargs.get("shell")


def test_timeout():
    def run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 15)

    with pytest.raises(BluetoothError, match="Tiempo"):
        BluetoothController(runner=run).connect(ADDR)


def test_rish_inexistente():
    def run(cmd, **kwargs):
        raise FileNotFoundError("rish")

    with pytest.raises(BluetoothError, match="rish"):
        BluetoothController(runner=run).connect(ADDR)


# --- Endpoints ---


class FakeController:
    def __init__(self):
        self.connected = False
        self.fail = False
        self.fail_status = False

    def connect(self, address):
        if self.fail:
            raise BluetoothError("no se pudo")
        self.connected = True

    def disconnect(self, address):
        if self.fail:
            raise BluetoothError("no se pudo")
        self.connected = False

    def is_connected(self, address):
        if self.fail_status:
            raise BluetoothError("sin estado")
        return self.connected


@pytest.fixture
def ctl():
    return FakeController()


@pytest.fixture
def bt_client(ctl):
    return TestClient(
        create_app(
            devices={"lamp": FakeDevice("lamp", "Lámpara")},
            token=TOKEN,
            bluetooth_targets={"spk": BluetoothTarget("spk", "Parlantes", ADDR)},
            bluetooth_controller=ctl,
        )
    )


def test_endpoints_requieren_auth(bt_client):
    assert bt_client.get("/bluetooth").status_code == 401
    assert bt_client.post("/bluetooth/spk/connect").status_code == 401
    assert bt_client.post("/bluetooth/spk/disconnect").status_code == 401


def test_list(bt_client):
    r = bt_client.get("/bluetooth", headers=HEADERS)
    assert r.json() == [{"id": "spk", "name": "Parlantes", "connected": False}]


def test_list_estado_no_disponible(bt_client, ctl):
    ctl.fail_status = True
    r = bt_client.get("/bluetooth", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()[0]["connected"] is None


def test_connect_y_disconnect(bt_client):
    r = bt_client.post("/bluetooth/spk/connect", headers=HEADERS)
    assert r.json() == {"id": "spk", "name": "Parlantes", "connected": True}
    r = bt_client.post("/bluetooth/spk/disconnect", headers=HEADERS)
    assert r.json()["connected"] is False


def test_id_inexistente(bt_client):
    assert bt_client.post("/bluetooth/zzz/connect", headers=HEADERS).status_code == 404
    assert bt_client.post("/bluetooth/zzz/disconnect", headers=HEADERS).status_code == 404


def test_error_503(bt_client, ctl):
    ctl.fail = True
    r = bt_client.post("/bluetooth/spk/connect", headers=HEADERS)
    assert r.status_code == 503
    assert "no se pudo" in r.json()["detail"]


# --- Configuración ---


def write(tmp_path, text):
    p = tmp_path / "devices.yaml"
    p.write_text(text)
    return p


def test_config_sin_seccion(tmp_path):
    assert config.load_bluetooth(write(tmp_path, "devices: []\n")) == {}


def test_config_ok_con_interpolacion(tmp_path, monkeypatch):
    monkeypatch.setenv("BT_ADDR", ADDR)
    p = write(tmp_path, "bluetooth:\n  - {id: spk, name: Parlantes, address: '${BT_ADDR}'}\n")
    assert config.load_bluetooth(p) == {"spk": BluetoothTarget("spk", "Parlantes", ADDR)}


def test_config_duplicados(tmp_path):
    p = write(
        tmp_path,
        f"bluetooth:\n  - {{id: a, name: A, address: '{ADDR}'}}\n"
        f"  - {{id: a, name: B, address: '{ADDR}'}}\n",
    )
    with pytest.raises(ValueError, match="duplicado"):
        config.load_bluetooth(p)


def test_config_direccion_invalida(tmp_path):
    p = write(tmp_path, "bluetooth:\n  - {id: a, name: A, address: 'nope'}\n")
    with pytest.raises(ValueError, match="inválida"):
        config.load_bluetooth(p)


class SlowController(FakeController):
    """La conexión real tarda: is_connected cambia tras unas consultas."""

    def __init__(self, delay_polls):
        super().__init__()
        self.delay_polls = delay_polls
        self.target = False

    def connect(self, address):
        self.target = True

    def disconnect(self, address):
        self.target = False

    def is_connected(self, address):
        if self.delay_polls > 0:
            self.delay_polls -= 1
            return not self.target
        return self.target


def test_connect_espera_a_que_el_estado_cambie(monkeypatch):
    monkeypatch.setattr("app.main.time.sleep", lambda s: None)
    ctl = SlowController(delay_polls=2)
    client = TestClient(
        create_app(
            devices={},
            token=TOKEN,
            bluetooth_targets={"spk": BluetoothTarget("spk", "Parlantes", ADDR)},
            bluetooth_controller=ctl,
        )
    )
    r = client.post("/bluetooth/spk/connect", headers=HEADERS)
    assert r.status_code == 200 and r.json()["connected"] is True


def test_devices_inyectados_no_leen_config_real(monkeypatch):
    def boom(path):
        raise AssertionError("no debe leer la configuración real")

    monkeypatch.setattr(config, "load_bluetooth", boom)
    create_app(devices={}, token=TOKEN)


def test_rish_sin_tty_responde_por_stderr():
    def run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="status true\n")

    c = BluetoothController(runner=run, rish="/x/rish", dex="/x/b.dex")
    assert c.is_connected(ADDR) is True


def test_available_true_cuando_rish_responde():
    def run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="ok\n")

    assert BluetoothController(runner=run, rish="/x/rish").available() is True


def test_available_false_si_rish_falla_o_no_existe():
    def falla(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Shizuku not running")

    def no_existe(cmd, **kwargs):
        raise FileNotFoundError

    assert BluetoothController(runner=falla, rish="/x/rish").available() is False
    assert BluetoothController(runner=no_existe, rish="/x/rish").available() is False


def test_health_informa_bluetooth(ctl):
    ctl.up = False
    ctl.available = lambda: ctl.up
    client = TestClient(
        create_app(
            devices={},
            token=TOKEN,
            bluetooth_targets={"spk": BluetoothTarget("spk", "Parlantes", ADDR)},
            bluetooth_controller=ctl,
        )
    )
    assert client.get("/health").json() == {"status": "ok", "bluetooth": "unavailable"}


def test_health_cachea_la_consulta(ctl):
    calls = []
    ctl.available = lambda: calls.append(1) or True
    client = TestClient(
        create_app(
            devices={},
            token=TOKEN,
            bluetooth_targets={"spk": BluetoothTarget("spk", "Parlantes", ADDR)},
            bluetooth_controller=ctl,
        )
    )
    for _ in range(3):
        assert client.get("/health").json()["bluetooth"] == "ok"
    assert len(calls) == 1


def test_health_sin_bluetooth_no_lo_menciona():
    client = TestClient(create_app(devices={}, token=TOKEN))
    assert client.get("/health").json() == {"status": "ok"}
