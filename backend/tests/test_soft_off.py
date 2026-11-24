from fastapi.testclient import TestClient

from app.devices.fake import FakeDevice
from app.devices.registry import build_device
from app.main import create_app
from app.media import CommandQueue
from app.now_playing import NowPlaying
from app.scenes import SceneContext, parse_scenes, run_scene
from app.soft_off import ANDROID_STEPS, FadeScheduler, SoftPower

TOKEN = "t"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


class FakeTimer:
    def __init__(self, interval, function, args):
        self.interval, self.function, self.args = interval, function, args
        self.started = self.cancelled = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def fire(self):
        self.function(*self.args)


class Env:
    def __init__(self, playing=True, volume=80, audio=True):
        self.events: list[str] = []
        self.queue = CommandQueue()
        self.np = NowPlaying(playing=playing, volume=volume)
        self.timers: list[FakeTimer] = []
        self.sleeps: list[float] = []

        def make_timer(interval, function, args):
            t = FakeTimer(interval, function, args)
            self.timers.append(t)
            return t

        self.fade = FadeScheduler(
            self.queue, self.np, sleep=self.sleeps.append, timer_factory=make_timer
        )
        self.soft = SoftPower(self.queue, self.np, self.fade, sleep=self._sleep)
        self.dev = FakeDevice("spk", "Parlantes", initially_on=True)
        self.dev.audio = audio
        orig_off = self.dev.off
        self.dev.off = lambda: (self.events.append(f"off:{len(self.queue.after(0))}"), orig_off())

    def _sleep(self, s):
        self.events.append(f"sleep:{s}")

    def cmds(self):
        return [(c.action, c.value) for c in self.queue.after(0)]


def test_build_device_audio():
    d = build_device({"type": "fake", "id": "a", "name": "A", "audio": True})
    assert d.audio is True
    assert build_device({"type": "fake", "id": "b", "name": "B"}).audio is False


def test_off_with_music_pauses_first():
    e = Env()
    e.soft.off(e.dev)
    assert e.cmds() == [("pause", None)]
    assert e.events == ["sleep:1.5", "off:1"]


def test_off_without_music_is_direct():
    e = Env(playing=False)
    e.soft.off(e.dev)
    assert e.cmds() == [] and e.events == ["off:0"]


def test_off_hard_and_non_audio_are_direct():
    e = Env()
    e.soft.off(e.dev, hard=True)
    assert e.cmds() == [] and e.events == ["off:0"]
    e = Env(audio=False)
    e.soft.off(e.dev)
    assert e.cmds() == [] and e.events == ["off:0"]


def _client(e: Env, **kw) -> TestClient:
    app = create_app(
        {"spk": e.dev}, TOKEN, scenes=kw.get("scenes"), battery_watch=False, sleep=e._sleep
    )
    return TestClient(app)


def _play(c: TestClient, playing=True):
    c.put("/now-playing", headers=HEADERS, json={"playing": playing, "title": "x", "volume": 50})


def _queued(c: TestClient):
    return [x["action"] for x in c.get("/media/commands", headers=HEADERS).json()]


def test_api_power_off_soft_and_hard():
    e = Env()
    with _client(e) as c:
        _play(c)
        assert c.post("/devices/spk/power", headers=HEADERS, json={"on": False}).status_code == 200
        assert _queued(c) == ["pause"]
        assert [x.split(":")[0] for x in e.events] == ["sleep", "off"]
        e.events.clear()
        r = c.post("/devices/spk/power?hard=true", headers=HEADERS, json={"on": False})
        assert r.status_code == 200 and [x.split(":")[0] for x in e.events] == ["off"]
        assert _queued(c) == ["pause"]  # sin pausa nueva


def test_api_toggle_off_is_soft():
    e = Env()
    with _client(e) as c:
        _play(c)
        c.post("/devices/spk/toggle", headers=HEADERS)
        assert _queued(c) == ["pause"] and e.events[0] == "sleep:1.5"


def test_scene_power_off_is_soft():
    e = Env()
    steps = parse_scenes({"s": [{"power": {"device": "spk", "on": False}}]}, ["spk"], [])["s"]
    ctx = SceneContext({"spk": e.dev}, None, {}, e.queue, sleep=e._sleep, power=e.soft)  # type: ignore[arg-type]
    assert run_scene(steps, ctx)[0]["ok"]
    assert e.cmds() == [("pause", None)] and e.events == ["sleep:1.5", "off:1"]


def test_scene_toggle_off_is_soft():
    e = Env()
    steps = parse_scenes({"s": [{"toggle": {"device": "spk"}}]}, ["spk"], [])["s"]
    ctx = SceneContext({"spk": e.dev}, None, {}, e.queue, sleep=e._sleep, power=e.soft)  # type: ignore[arg-type]
    run_scene(steps, ctx)
    assert e.cmds() == [("pause", None)]


def test_fade_scheduled_with_lead():
    e = Env()
    e.soft.set_timer(e.dev, 45)
    assert e.dev.timer == 2700
    assert len(e.timers) == 1 and e.timers[0].started
    assert e.timers[0].interval == 2700 - 60


def test_no_fade_under_two_minutes_or_non_audio():
    e = Env()
    e.soft.set_timer(e.dev, 1)
    assert e.timers == []
    e = Env(audio=False)
    e.soft.set_timer(e.dev, 45)
    assert e.timers == []


def test_scene_timer_schedules_fade():
    e = Env()
    steps = parse_scenes({"s": [{"timer": {"device": "spk", "minutes": 30}}]}, ["spk"], [])["s"]
    ctx = SceneContext({"spk": e.dev}, None, {}, e.queue, power=e.soft)  # type: ignore[arg-type]
    run_scene(steps, ctx)
    assert e.timers[0].interval == 1800 - 60


def test_fade_sequence():
    e = Env(volume=80)
    e.soft.set_timer(e.dev, 30)
    e.timers[0].fire()
    cmds = e.cmds()
    vols = [v for a, v in cmds if a == "volume"]
    body, restore = vols[:-1], vols[-1]
    assert restore == 80
    assert body == sorted(body, reverse=True) and body[0] < 80 and body[-1] == 0
    assert all(v in ANDROID_STEPS for v in body)
    assert cmds[-2] == ("pause", None) and cmds[-1] == ("volume", 80)
    assert e.sleeps[-1] == 2 and abs(sum(e.sleeps[:-1]) - 45) < 1e-6
    assert ("pause", None) in cmds


def test_fade_without_music_does_nothing():
    e = Env(playing=False)
    e.soft.set_timer(e.dev, 30)
    e.timers[0].fire()
    assert e.cmds() == []
    e = Env(volume=None)
    e.soft.set_timer(e.dev, 30)
    e.timers[0].fire()
    assert e.cmds() == []


def test_fade_cancellation():
    e = Env()
    e.soft.set_timer(e.dev, 30)
    e.soft.set_timer(e.dev, 0)  # minutes 0 cancela
    assert e.timers[0].cancelled and len(e.timers) == 1
    e.soft.set_timer(e.dev, 30)
    e.soft.set_timer(e.dev, 20)  # reemplaza
    assert e.timers[1].cancelled and not e.timers[2].cancelled
    e.soft.off(e.dev)  # apagar cancela
    assert e.timers[2].cancelled
    e.timers[2].fire()
    assert [a for a, _ in e.cmds() if a == "volume"] == []
