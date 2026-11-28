import pytest
from fastapi.testclient import TestClient

from app import config
from app.bluetooth import BluetoothError, BluetoothTarget
from app.devices.fake import FakeDevice
from app.main import create_app
from app.media import CommandQueue, MediaCommand
from app.scenes import SceneContext, SceneError, parse_scenes, run_scene

TOKEN = "test-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
TARGET = BluetoothTarget("spk", "Parlantes", "AA:BB:CC:DD:EE:FF")


class FakeBt:
    def __init__(self, connected: bool = False, fail: bool = False) -> None:
        self.connected = connected
        self.fail = fail
        self.calls: list[str] = []

    def is_connected(self, address: str) -> bool:
        return self.connected

    def connect(self, address: str) -> None:
        self.calls.append("connect")
        if self.fail:
            raise BluetoothError("falló")
        self.connected = True

    def disconnect(self, address: str) -> None:
        self.calls.append("disconnect")
        self.connected = False

    def available(self) -> bool:
        return True


def parse(raw):
    return parse_scenes(raw, ["lamp"], ["spk"])


def make_ctx(bt=None, devices=None):
    sleeps: list[float] = []
    ctx = SceneContext(
        devices
        or {"lamp": FakeDevice("lamp", "Lámpara"), "dead": FakeDevice("dead", "x", online=False)},
        bt or FakeBt(),
        {"spk": TARGET},
        CommandQueue(),
        sleep=sleeps.append,
    )
    return ctx, sleeps


# --- órdenes nuevas de media


def test_play_search_valido_y_focus_por_defecto():
    assert MediaCommand(action="play_search", query="Soda").focus == "any"
    assert MediaCommand(action="play_search", query="x", focus="artist").focus == "artist"
    assert MediaCommand(action="wake").query is None


@pytest.mark.parametrize(
    "body",
    [
        {"action": "play_search"},
        {"action": "play_search", "query": ""},
        {"action": "play_search", "query": "   "},
        {"action": "play_search", "query": "a" * 201},
        {"action": "play_search", "query": "x", "focus": "track"},
        {"action": "next", "query": "x"},
        {"action": "wake", "focus": "any"},
        {"action": "wake", "value": 3},
    ],
)
def test_ordenes_invalidas(body):
    client = TestClient(create_app(devices={}, token=TOKEN))
    assert client.post("/media/command", headers=HEADERS, json=body).status_code == 422


def test_cola_devuelve_query_y_focus():
    client = TestClient(create_app(devices={}, token=TOKEN))
    client.post("/media/command", headers=HEADERS, json={"action": "play_search", "query": "Q"})
    client.post("/media/command", headers=HEADERS, json={"action": "next"})
    cmds = client.get("/media/commands", headers=HEADERS).json()
    assert (cmds[0]["query"], cmds[0]["focus"]) == ("Q", "any")
    assert (cmds[1]["query"], cmds[1]["focus"]) == (None, None)


# --- validación al cargar


def test_escenas_ausentes():
    assert parse(None) == {}


def test_escena_valida():
    scenes = parse(
        {
            "mi-escena_1": [
                {"power": {"device": "lamp", "on": True}},
                {"toggle": {"device": "lamp"}},
                {"bluetooth": {"id": "spk", "connect": True}},
                {"media": {"action": "play_search", "query": "x"}},
                {"wake": None},
                {"wait": 2.5},
            ]
        }
    )
    assert [s.kind for s in scenes["mi-escena_1"]] == [
        "power", "toggle", "bluetooth", "media", "wake", "wait",
    ]  # fmt: skip


@pytest.mark.parametrize(
    "raw, texto",
    [
        ({"Mala Escena": []}, "Nombre de escena"),
        ({"a": [{"power": {"device": "lamp", "on": True}, "wait": 1}]}, "una sola clave"),
        ({"a": ["power"]}, "dict"),
        ({"a": [{"bailar": 1}]}, "desconocido"),
        ({"a": [{"wait": 31}]}, "entre 0 y 30"),
        ({"a": [{"wait": -1}]}, "entre 0 y 30"),
        ({"a": [{"wait": "2"}]}, "número"),
        ({"a": [{"power": {"device": "lamp"}}]}, "on"),
        ({"a": [{"power": {"device": "lamp", "on": "si"}}]}, "on"),
        ({"a": [{"power": {"on": True}}]}, "device"),
        ({"a": [{"toggle": {}}]}, "device"),
        ({"a": [{"bluetooth": {"id": "spk"}}]}, "connect"),
        ({"a": [{"bluetooth": {"connect": True}}]}, "id"),
        ({"a": [{"media": {"action": "volume"}}]}, "media inválido"),
        ({"a": [{"media": {"action": "play_search"}}]}, "media inválido"),
        ({"a": [{"power": {"device": "nada", "on": True}}]}, "válidos: lamp"),
        ({"a": [{"toggle": {"device": "nada"}}]}, "válidos: lamp"),
        ({"a": [{"bluetooth": {"id": "nada", "connect": True}}]}, "válidos: spk"),
    ],
)
def test_escenas_invalidas(raw, texto):
    with pytest.raises(SceneError, match=texto):
        parse(raw)


def test_load_scenes_desde_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTISTA", "Soda")
    f = tmp_path / "d.yaml"
    f.write_text('scenes:\n  s:\n    - media: { action: play_search, query: "${ARTISTA}" }\n')
    scenes = config.load_scenes(f, [], [])
    assert scenes["s"][0].args["command"].query == "Soda"
    f.write_text("devices: []\n")
    assert config.load_scenes(f, [], []) == {}


# --- ejecución


def test_orden_y_efectos():
    ctx, sleeps = make_ctx()
    steps = parse(
        {
            "e": [
                {"power": {"device": "lamp", "on": True}},
                {"wait": 3},
                {"toggle": {"device": "lamp"}},
                {"wake": None},
            ]
        }
    )["e"]
    res = run_scene(steps, ctx)
    assert [r["step"] for r in res] == ["power", "wait", "toggle", "wake"]
    assert all(r["ok"] for r in res)
    assert sleeps == [3]
    assert ctx.devices["lamp"].status().on is False
    assert [c.action for c in ctx.queue.after(0)] == ["wake"]


def test_fallo_no_detiene():
    ctx, _ = make_ctx()
    ctx.devices["dead"] = FakeDevice("dead", "x", online=False)
    steps = parse_scenes(
        {
            "e": [
                {"power": {"device": "dead", "on": True}},
                {"power": {"device": "lamp", "on": True}},
            ]
        },
        ["lamp", "dead"],
        [],
    )["e"]
    res = run_scene(steps, ctx)
    assert [r["ok"] for r in res] == [False, True]
    assert ctx.devices["lamp"].status().on is True


def test_bluetooth_ya_conectado_es_ok():
    bt = FakeBt(connected=True)
    ctx, _ = make_ctx(bt)
    res = run_scene(parse({"e": [{"bluetooth": {"id": "spk", "connect": True}}]})["e"], ctx)
    assert res[0]["ok"] is True and bt.calls == []


def test_bluetooth_conecta_y_falla():
    bt = FakeBt()
    ctx, _ = make_ctx(bt)
    steps = parse({"e": [{"bluetooth": {"id": "spk", "connect": True}}]})["e"]
    assert run_scene(steps, ctx)[0]["ok"] is True and bt.calls == ["connect"]
    ctx, _ = make_ctx(FakeBt(fail=True))
    assert run_scene(steps, ctx)[0]["ok"] is False


def test_media_encola():
    ctx, _ = make_ctx()
    steps = parse({"e": [{"media": {"action": "play_search", "query": "Q", "focus": "album"}}]})[
        "e"
    ]
    res = run_scene(steps, ctx)
    assert res[0]["ok"] is True
    (cmd,) = ctx.queue.after(0)
    assert (cmd.action, cmd.query, cmd.focus) == ("play_search", "Q", "album")


# --- endpoints


@pytest.fixture
def client() -> TestClient:
    scenes = parse(
        {
            "ok": [{"power": {"device": "lamp", "on": True}}, {"wake": None}],
            "mixta": [{"toggle": {"device": "lamp"}}, {"wait": 0}],
        }
    )
    devices = {"lamp": FakeDevice("lamp", "Lámpara")}
    return TestClient(
        create_app(devices=devices, token=TOKEN, scenes=scenes, bluetooth_controller=FakeBt())
    )


def test_endpoints_auth(client):
    assert client.get("/scenes").status_code == 401
    assert client.post("/scenes/ok").status_code == 401


def test_listar(client):
    r = client.get("/scenes", headers=HEADERS)
    assert r.json() == [{"name": "ok", "steps": 2}, {"name": "mixta", "steps": 2}]


def test_ejecutar_y_404(client):
    assert client.post("/scenes/nada", headers=HEADERS).status_code == 404
    r = client.post("/scenes/ok", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "ok" and body["ok"] is True
    assert [s["step"] for s in body["steps"]] == ["power", "wake"]
    cmds = client.get("/media/commands", headers=HEADERS).json()
    assert [c["action"] for c in cmds] == ["wake"]


def test_ok_global_falso():
    devices = {"dead": FakeDevice("dead", "x", online=False)}
    scenes = parse_scenes({"e": [{"toggle": {"device": "dead"}}]}, ["dead"], [])
    c = TestClient(create_app(devices=devices, token=TOKEN, scenes=scenes))
    body = c.post("/scenes/e", headers=HEADERS).json()
    assert body["ok"] is False and body["steps"][0]["ok"] is False


def test_power_on_sin_comillas_en_yaml(tmp_path):
    # YAML 1.1 lee la clave `on` como el booleano True: debe funcionar igual
    import yaml

    from app.scenes import parse_scenes

    raw = yaml.safe_load("a:\n  - power: { device: lamp, on: true }\n  - wake\n")
    scenes = parse_scenes(raw, {"lamp"}, set())
    assert len(scenes["a"]) == 2


# --- timer y mode


@pytest.mark.parametrize(
    "step",
    [
        {"timer": {"device": "nada", "minutes": 5}},
        {"timer": {"device": "lamp", "minutes": 721}},
        {"timer": {"device": "lamp", "minutes": -1}},
        {"timer": {"device": "lamp", "minutes": "5"}},
        {"timer": {"device": "lamp", "minutes": True}},
        {"timer": {"minutes": 5}},
        {"timer": 5},
        {"mode": "tarde"},
        {"mode": {"x": 1}},
    ],
)
def test_timer_mode_invalidos(step):
    with pytest.raises(SceneError):
        parse({"s": [step]})


def test_timer_mode_validos():
    steps = parse({"s": [{"timer": {"device": "lamp", "minutes": 720}}, {"mode": "auto"}]})["s"]
    assert [s.kind for s in steps] == ["timer", "mode"]


def test_ejecuta_timer_y_mode():
    ctx, _ = make_ctx()
    steps = parse({"s": [{"timer": {"device": "lamp", "minutes": 45}}, {"mode": "night"}]})["s"]
    res = run_scene(steps, ctx)
    assert all(r["ok"] for r in res)
    assert ctx.devices["lamp"].timer == 2700
    assert ctx.mode.current()["mode"] == "night"


def test_timer_fallos_no_detienen():
    ctx, _ = make_ctx()
    steps = parse_scenes(
        {"s": [{"timer": {"device": "dead", "minutes": 5}}, {"mode": "day"}]},
        ["dead"],
        [],
    )["s"]
    res = run_scene(steps, ctx)
    assert [r["ok"] for r in res] == [False, True]


def test_resumen_legible(client):
    body = client.post("/scenes/ok", headers=HEADERS).json()
    assert body["summary"] == "Ok ✓"


def test_resumen_con_fallo():
    devices = {"dead": FakeDevice("dead", "x", online=False)}
    scenes = parse_scenes({"noche": [{"toggle": {"device": "dead"}}]}, ["dead"], [])
    c = TestClient(create_app(devices=devices, token=TOKEN, scenes=scenes))
    summary = c.post("/scenes/noche", headers=HEADERS).json()["summary"]
    assert summary.startswith("Noche: falló toggle")


def test_ultimo_evento(client):
    assert client.get("/scenes/last", headers=HEADERS).json() is None
    client.post("/scenes/ok", headers=HEADERS)
    last = client.get("/scenes/last", headers=HEADERS).json()
    assert last["name"] == "ok" and last["ok"] is True and last["summary"] == "Ok ✓"
    assert isinstance(last["id"], int) and last["at"]
    client.post("/scenes/mixta", headers=HEADERS)
    assert client.get("/scenes/last", headers=HEADERS).json()["id"] == last["id"] + 1


class RecordingNotifier:
    def __init__(self):
        self.sent = []

    def send(self, alert):
        self.sent.append(alert)
        return True


def test_escena_notifica_por_ntfy():
    import time as _time

    devices = {"lamp": FakeDevice("lamp", "Lámpara"), "dead": FakeDevice("dead", "x", online=False)}
    scenes = parse_scenes(
        {
            "noche": [{"power": {"device": "lamp", "on": True}}],
            "mala": [{"toggle": {"device": "dead"}}],
        },
        ["lamp", "dead"],
        [],
    )
    n = RecordingNotifier()
    c = TestClient(create_app(devices=devices, token=TOKEN, scenes=scenes, notifier=n))
    c.post("/scenes/noche", headers=HEADERS)
    c.post("/scenes/mala", headers=HEADERS)
    for _ in range(50):  # se envía en segundo plano
        if len(n.sent) == 2:
            break
        _time.sleep(0.02)
    ok, bad = n.sent
    assert ok.title == "Noche ✓" and ok.priority == "default"
    assert bad.title.startswith("Mala: falló") and bad.priority == "high"


def test_wait_condicional_solo_si_se_acaba_de_encender():
    raw = {
        "s": [
            {"power": {"device": "lamp", "on": True}},
            {"wait": {"seconds": 4, "if_powered_on": True}},
        ]
    }
    steps = parse(raw)["s"]
    # Apagado → se enciende → espera
    ctx, sleeps = make_ctx()
    res = run_scene(steps, ctx)
    assert sleeps == [4] and res[1]["ok"]
    # Ya encendido → no espera
    lamp = FakeDevice("lamp", "Lámpara", initially_on=True)
    ctx2, sleeps2 = make_ctx(devices={"lamp": lamp})
    res2 = run_scene(steps, ctx2)
    assert sleeps2 == [] and res2[1]["ok"] and "omitida" in res2[1]["detail"]


def test_wait_numero_sigue_funcionando_y_dict_invalido():
    assert parse({"s": [{"wait": 2}]})["s"][0].args == {"seconds": 2, "if_powered_on": False}
    for bad in ({"seconds": 99}, {"seconds": 2, "if_powered_on": "si"}, {"if_powered_on": True}):
        with pytest.raises(SceneError):
            parse({"s": [{"wait": bad}]})


# --- light


@pytest.mark.parametrize(
    "step",
    [
        {"light": {"device": "nada", "brightness": 5}},
        {"light": {"brightness": 5}},
        {"light": {"device": "lamp"}},
        {"light": {"device": "lamp", "brightness": 0}},
        {"light": {"device": "lamp", "hue": 10}},
        {"light": {"device": "lamp", "hue": 10, "saturation": 5, "color_temp": 3000}},
        {"light": {"device": "lamp", "brillo": 5}},
        {"light": 5},
    ],
)
def test_light_invalidos(step):
    with pytest.raises(SceneError):
        parse({"s": [step]})


def test_ejecuta_light():
    foco = FakeDevice("foco", "Foco", light=True)
    ctx, _ = make_ctx(devices={"foco": foco, "lamp": FakeDevice("lamp", "L")})
    steps = parse_scenes(
        {
            "s": [
                {"light": {"device": "foco", "brightness": 20, "color_temp": 2500}},
                {"light": {"device": "lamp", "brightness": 20}},
                {"light": {"device": "foco", "color_temp": 9000}},
            ]
        },
        ["foco", "lamp"],
        [],
    )["s"]
    res = run_scene(steps, ctx)
    assert [r["ok"] for r in res] == [True, False, False]
    assert res[0]["detail"] == "foco: brillo 20 %, 2500 K"
    st = foco.status()
    assert st.on is True and (st.light.brightness, st.light.color_temp) == (20, 2500)
