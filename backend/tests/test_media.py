import asyncio

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.media import CommandQueue, MediaCommand

TOKEN = "test-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(devices={}, token=TOKEN))


def post(client: TestClient, **body: object):
    return client.post("/media/command", headers=HEADERS, json=body)


def test_auth_required(client: TestClient) -> None:
    assert client.post("/media/command", json={"action": "next"}).status_code == 401
    assert client.get("/media/commands").status_code == 401


def test_post_returns_202_and_increasing_ids(client: TestClient) -> None:
    r = post(client, action="next")
    assert (r.status_code, r.json()) == (202, {"id": 1})
    assert post(client, action="volume", value=30).json() == {"id": 2}


@pytest.mark.parametrize(
    "body",
    [
        {"action": "volume"},
        {"action": "volume", "value": 101},
        {"action": "volume", "value": -1},
        {"action": "next", "value": 5},
        {"action": "bailar"},
    ],
)
def test_invalid_commands(client: TestClient, body: dict[str, object]) -> None:
    assert post(client, **body).status_code == 422


def test_list_and_after(client: TestClient) -> None:
    post(client, action="next")
    post(client, action="volume", value=30)
    r = client.get("/media/commands", headers=HEADERS)
    cmds = r.json()
    assert [(c["id"], c["action"], c["value"]) for c in cmds] == [
        (1, "next", None),
        (2, "volume", 30),
    ]
    assert "created_at" in cmds[0]
    r = client.get("/media/commands?after=1", headers=HEADERS)
    assert [c["id"] for c in r.json()] == [2]
    assert client.get("/media/commands?after=2", headers=HEADERS).json() == []


def test_wait_zero_returns_immediately(client: TestClient) -> None:
    r = client.get("/media/commands?after=0&wait=0", headers=HEADERS)
    assert r.json() == []


def test_wait_is_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[float] = []

    async def fake_wait(self: CommandQueue, after: int, timeout: float) -> list:
        seen.append(timeout)
        return []

    monkeypatch.setattr(CommandQueue, "wait_after", fake_wait)
    c = TestClient(create_app(devices={}, token=TOKEN))
    c.get("/media/commands?wait=999", headers=HEADERS)
    c.get("/media/commands?wait=-5", headers=HEADERS)
    assert seen == [30, 0]


def test_expiration_with_fake_clock() -> None:
    clock = FakeClock()
    q = CommandQueue(ttl=10, clock=clock)
    q.add(MediaCommand(action="next"))
    clock.now = 9
    q.add(MediaCommand(action="pause"))
    assert [c.id for c in q.after(0)] == [1, 2]
    clock.now = 11
    assert [c.id for c in q.after(0)] == [2]
    clock.now = 25
    assert q.after(0) == []
    # los ids siguen creciendo
    assert q.add(MediaCommand(action="play")) == 3


def test_max_queued() -> None:
    q = CommandQueue()
    for _ in range(60):
        q.add(MediaCommand(action="next"))
    ids = [c.id for c in q.after(0)]
    assert len(ids) == 50
    assert ids[-1] == 60


def test_wait_after_wakes_on_new_command() -> None:
    async def scenario() -> list[int]:
        q = CommandQueue()
        waiter = asyncio.create_task(q.wait_after(0, 5))
        await asyncio.sleep(0.05)
        assert not waiter.done()
        q.add(MediaCommand(action="next"))
        return [c.id for c in await asyncio.wait_for(waiter, 1)]

    assert asyncio.run(scenario()) == [1]


def test_wait_after_times_out_empty() -> None:
    async def scenario() -> list:
        return await CommandQueue().wait_after(0, 0.05)

    assert asyncio.run(scenario()) == []


def test_orden_launch_exige_paquete_valido():
    from app.media import MediaCommand

    cmd = MediaCommand(action="launch", package="com.spotify.music")
    assert cmd.package == "com.spotify.music"
    for bad in (
        {"action": "launch"},
        {"action": "launch", "package": "rm -rf /"},
        {"action": "pause", "package": "com.spotify.music"},
    ):
        try:
            MediaCommand(**bad)
        except ValueError:
            continue
        raise AssertionError(f"debía rechazar {bad}")


def test_launch_viaja_en_la_cola():
    from app.media import CommandQueue, MediaCommand

    q = CommandQueue()
    q.add(MediaCommand(action="launch", package="com.spotify.music"))
    assert q.after(0)[0].to_json()["package"] == "com.spotify.music"
