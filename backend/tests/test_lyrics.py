import urllib.parse

import pytest
from fastapi.testclient import TestClient

from app.lyrics import LyricsClient, LyricsUnavailable, parse_lrc, strip_version
from app.main import create_app

TOKEN = "test-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

HIT = {"syncedLyrics": "[00:01.50] hola\n[00:03.00] mundo", "plainLyrics": "hola\nmundo"}


class FakeFetcher:
    """Responde por prefijo de ruta; None = 404; excepción = fallo de red."""

    def __init__(self, **routes: object) -> None:
        self.routes = routes
        self.urls: list[str] = []

    def __call__(self, url: str) -> object:
        self.urls.append(url)
        path = urllib.parse.urlparse(url).path.rsplit("/", 1)[-1]
        out = self.routes.get(path)
        if isinstance(out, Exception):
            raise out
        return out

    def params(self, i: int) -> dict[str, str]:
        return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.urls[i]).query))


def test_parse_lrc_multiple_tags_sorted() -> None:
    lrc = "[00:10.00] b\n[00:02.00][00:20.00] a\n"
    assert parse_lrc(lrc) == [
        {"t": 2000, "line": "a"},
        {"t": 10000, "line": "b"},
        {"t": 20000, "line": "a"},
    ]


def test_parse_lrc_ignores_metadata_and_plain_lines() -> None:
    lrc = "[ar:Artista]\n[ti:Titulo]\nsin marca\n[01:02.03] x"
    assert parse_lrc(lrc) == [{"t": 62030, "line": "x"}]


def test_parse_lrc_fraction_precision() -> None:
    lrc = "[00:01.5] a\n[00:01.50] b\n[00:01.500] c\n[00:01.123] d\n[00:05] e"
    assert sorted(x["t"] for x in parse_lrc(lrc)) == [1123, 1500, 1500, 1500, 5000]


@pytest.mark.parametrize(
    ("title", "short"),
    [
        ("Song - Remastered 2011", "Song"),
        ("Song – Live", "Song"),
        ("Song — Mono", "Song"),
        ("Song (feat. X)", "Song"),
        ("Song [Deluxe]", "Song"),
        ("Song", "Song"),
        ("Semi-colon", "Semi-colon"),
    ],
)
def test_strip_version(title: str, short: str) -> None:
    assert strip_version(title) == short


def test_get_first_with_album_and_rounded_duration() -> None:
    f = FakeFetcher(get=HIT)
    r = LyricsClient(f).lookup("T", "A", "L", 215600)
    assert r == {
        "synced": [{"t": 1500, "line": "hola"}, {"t": 3000, "line": "mundo"}],
        "plain": "hola\nmundo",
        "instrumental": False,
    }
    assert len(f.urls) == 1
    assert f.urls[0].startswith("https://lrclib.net/api/get?")
    assert f.params(0) == {
        "track_name": "T",
        "artist_name": "A",
        "album_name": "L",
        "duration": "216",
    }


def test_get_omits_unknown_album_and_duration() -> None:
    f = FakeFetcher(get=HIT)
    LyricsClient(f).lookup("T", "A")
    assert f.params(0) == {"track_name": "T", "artist_name": "A"}


def test_order_get_then_stripped_then_search() -> None:
    f = FakeFetcher(get=None, search=[HIT, {"plainLyrics": "otro"}])
    r = LyricsClient(f).lookup("Song - Live", "A", "L", 100000)
    assert r is not None and r["plain"] == "hola\nmundo"
    assert [u.split("?")[0].rsplit("/", 1)[-1] for u in f.urls] == ["get", "get", "search"]
    assert f.params(0)["track_name"] == "Song - Live"
    assert f.params(1)["track_name"] == "Song"
    assert f.params(2) == {"track_name": "Song - Live", "artist_name": "A"}


def test_stripped_retry_stops_on_hit() -> None:
    answers = iter([None, HIT])
    calls: list[str] = []

    def fetch(url: str) -> object:
        calls.append(url)
        return next(answers)

    assert LyricsClient(fetch).lookup("Song (Live)", "A") is not None
    assert len(calls) == 2


def test_no_stripped_retry_when_title_has_no_suffix() -> None:
    f = FakeFetcher(get=None, search=[])
    assert LyricsClient(f).lookup("Song", "A") is None
    assert [u.split("?")[0].rsplit("/", 1)[-1] for u in f.urls] == ["get", "search"]


def test_instrumental_and_plain_only() -> None:
    inst = LyricsClient(FakeFetcher(get={"instrumental": True})).lookup("T", "A")
    assert inst == {"synced": None, "plain": None, "instrumental": True}
    plain = LyricsClient(FakeFetcher(get={"plainLyrics": "x", "syncedLyrics": None}))
    assert plain.lookup("T", "A") == {"synced": None, "plain": "x", "instrumental": False}


def test_cache_hits_and_negatives() -> None:
    f = FakeFetcher(get=HIT)
    c = LyricsClient(f)
    c.lookup("T", "A", "L")
    c.lookup("T", "A", "L")
    assert len(f.urls) == 1
    g = FakeFetcher(get=None, search=[])
    n = LyricsClient(g)
    assert n.lookup("T", "A") is None
    calls = len(g.urls)
    assert n.lookup("T", "A") is None
    assert len(g.urls) == calls


def test_cache_limited_to_50() -> None:
    f = FakeFetcher(get=HIT)
    c = LyricsClient(f)
    for i in range(51):
        c.lookup(f"T{i}", "A")
    n = len(f.urls)
    c.lookup("T50", "A")
    assert len(f.urls) == n
    c.lookup("T0", "A")  # ya expulsada
    assert len(f.urls) == n + 1


def test_errors_not_cached() -> None:
    f = FakeFetcher(get=LyricsUnavailable("x"))
    c = LyricsClient(f)
    for _ in range(2):
        with pytest.raises(LyricsUnavailable):
            c.lookup("T", "A")
    assert len(f.urls) == 2


# --- endpoint ---


def make_client(fetcher: FakeFetcher) -> TestClient:
    return TestClient(create_app(devices={}, token=TOKEN, lyrics_fetcher=fetcher))


def play(client: TestClient, **extra: object) -> None:
    body = {"playing": True, "title": "T", "artist": "A", "album": "L", **extra}
    assert client.put("/now-playing", headers=HEADERS, json=body).status_code == 200


def test_endpoint_requires_auth() -> None:
    assert make_client(FakeFetcher(get=HIT)).get("/lyrics").status_code == 401


def test_endpoint_404_when_nothing_playing() -> None:
    f = FakeFetcher(get=HIT)
    r = make_client(f).get("/lyrics", headers=HEADERS)
    assert r.status_code == 404
    assert r.json() == {"detail": "Sin letra para esta canción"}
    assert f.urls == []


def test_endpoint_ok_uses_now_playing() -> None:
    f = FakeFetcher(get=HIT)
    c = make_client(f)
    play(c, duration_ms=215000)
    r = c.get("/lyrics", headers=HEADERS)
    assert r.status_code == 200
    assert r.json() == {
        "title": "T",
        "artist": "A",
        "synced": [{"t": 1500, "line": "hola"}, {"t": 3000, "line": "mundo"}],
        "plain": "hola\nmundo",
        "instrumental": False,
        "source": "lrclib",
    }
    assert f.params(0)["duration"] == "215"


def test_endpoint_404_without_lyrics() -> None:
    c = make_client(FakeFetcher(get=None, search=[]))
    play(c)
    r = c.get("/lyrics", headers=HEADERS)
    assert r.status_code == 404
    assert r.json() == {"detail": "Sin letra para esta canción"}


def test_endpoint_503_on_network_error() -> None:
    c = make_client(FakeFetcher(get=LyricsUnavailable("sin red")))
    play(c)
    assert c.get("/lyrics", headers=HEADERS).status_code == 503
