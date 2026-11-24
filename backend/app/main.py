"""API FastAPI de selfRoomHub.

Arranque:
    uv run uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
"""

import asyncio
import contextlib
import html
import logging
import re
import secrets
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import config
from app.battery import BatteryError, BatteryMonitor
from app.battery_alerts import (
    Alert,
    BatteryWatcher,
    Notifier,
    advice,
    notifier_from_env,
    thresholds_from_env,
)
from app.bluetooth import BluetoothController, BluetoothError, BluetoothTarget
from app.devices.base import Device, DeviceError
from app.lyrics import LyricsClient, LyricsFetcher, LyricsUnavailable
from app.media import CommandQueue, MediaCommand
from app.mode import ModeState
from app.now_playing import ArtError, NowPlaying, NowPlayingUpdate
from app.routines import Window
from app.scenes import SceneContext, Step, run_scene
from app.soft_off import FadeScheduler, SoftPower
from app.spotify import SpotifyClient, SpotifyError

BT_WAIT_POLLS = 8
HEALTH_CACHE_S = 60
MAX_WAIT_S = 30
BATTERY_WATCH_EVERY_S = 60
NO_LYRICS = "Sin letra para esta canción"
PANEL_DIR = Path(__file__).parent / "panel"


class PowerRequest(BaseModel):
    on: bool


class SpotifyPlayRequest(BaseModel):
    query: str | None = None
    uri: str | None = None
    type: Literal["artist", "album", "playlist", "track"] = "artist"
    device: str | None = None
    shuffle: bool | None = None


class TimerRequest(BaseModel):
    minutes: int = Field(ge=0, le=720)


class ModeRequest(BaseModel):
    mode: Literal["day", "night", "auto"]


def _state(device: Device) -> dict[str, object]:
    st = device.status()
    return {
        "id": device.id,
        "name": device.name,
        "online": st.online,
        "on": st.on,
        "timer": st.timer,
    }


def _page(body: str) -> str:
    head = '<meta charset="utf-8"><meta name="viewport" content="width=device-width">'
    return f"<!doctype html>{head}<body>{body}</body>"


class PanelFiles(StaticFiles):
    """Archivos del panel sin caché fija: el kiosco ve cada cambio (revalida con ETag)."""

    async def get_response(self, path: str, scope):  # type: ignore[override]
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


class RedactSecrets(logging.Filter):
    """Tacha token, code y state de las URLs en el log de acceso (vinculación con Spotify)."""

    _pattern = re.compile(r"\b(token|code|state)=[^&\s]*")

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                self._pattern.sub(r"\1=***", a) if isinstance(a, str) else a for a in record.args
            )
        return True


logging.getLogger("uvicorn.access").addFilter(RedactSecrets())


def create_app(
    devices: dict[str, Device] | None = None,
    token: str | None = None,
    bluetooth_targets: dict[str, BluetoothTarget] | None = None,
    bluetooth_controller: BluetoothController | None = None,
    lyrics_fetcher: LyricsFetcher | None = None,
    battery: BatteryMonitor | None = None,
    notifier: Notifier | None = None,
    battery_watch: bool | None = None,
    scenes: dict[str, list[Step]] | None = None,
    spotify: SpotifyClient | None = None,
    routines: dict[str, list[Window]] | None = None,
    clock: Callable[[], datetime] = datetime.now,
    sleep: Callable[[float], None] = time.sleep,
) -> FastAPI:
    # Sin inyección se arranca de verdad: se lee .env y la configuración
    from_config = devices is None or token is None
    if from_config:
        config.load_env()
        if token is None:
            token = config.get_token()
        if devices is None:
            devices = config.load_devices(config.get_config_path())
    if bluetooth_targets is None:
        bluetooth_targets = config.load_bluetooth(config.get_config_path()) if from_config else {}
    bt_targets = bluetooth_targets
    if scenes is None:
        scenes = (
            config.load_scenes(config.get_config_path(), devices, bt_targets) if from_config else {}
        )
    scene_defs = scenes
    if routines is None:
        routines = config.load_routines(config.get_config_path(), scene_defs) if from_config else {}
    routine_defs = routines
    mode_state = ModeState.from_env(clock)
    bt = bluetooth_controller or BluetoothController()
    expected = token
    registry = devices

    bearer = HTTPBearer(auto_error=False)

    def auth(creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> None:
        if creds is None or not secrets.compare_digest(
            creds.credentials.encode(), expected.encode()
        ):
            raise HTTPException(status_code=401, detail="No autorizado")

    def get_device(device_id: str) -> Device:
        device = registry.get(device_id)
        if device is None:
            raise HTTPException(status_code=404, detail=f"Dispositivo no encontrado: {device_id}")
        return device

    def get_target(target_id: str) -> BluetoothTarget:
        target = bt_targets.get(target_id)
        if target is None:
            raise HTTPException(status_code=404, detail=f"Bluetooth no encontrado: {target_id}")
        return target

    def wait_connected(target: BluetoothTarget, expected: bool) -> None:
        # connect/disconnect responden al instante, pero el enlace real tarda ~2 s
        for _ in range(BT_WAIT_POLLS):
            try:
                if bt.is_connected(target.address) == expected:
                    return
            except BluetoothError:
                pass
            time.sleep(1)

    def bt_state(target: BluetoothTarget, strict: bool = False) -> dict[str, object]:
        try:
            connected: bool | None = bt.is_connected(target.address)
        except BluetoothError as e:
            if strict:
                raise HTTPException(status_code=503, detail=str(e)) from e
            connected = None
        return {"id": target.id, "name": target.name, "connected": connected}

    # Consultar rish tarda ~1 s: el estado del Bluetooth se reutiliza un rato
    bt_health: dict[str, float | bool] = {"at": float("-inf"), "ok": False}

    def bluetooth_available() -> bool:
        now = time.monotonic()
        if now - bt_health["at"] > HEALTH_CACHE_S:
            bt_health.update(at=now, ok=bt.available())
        return bool(bt_health["ok"])

    now_playing = NowPlaying()
    media_queue = CommandQueue()
    lyrics = LyricsClient(lyrics_fetcher)
    if spotify is None:
        spotify = SpotifyClient.from_env() if from_config else SpotifyClient(None)
    sp = spotify
    fade = FadeScheduler(media_queue, now_playing, sleep=sleep)
    soft = SoftPower(media_queue, now_playing, fade, sleep=sleep)
    scene_ctx = SceneContext(
        registry, bt, bt_targets, media_queue, spotify=sp, mode=mode_state, power=soft
    )

    battery_monitor = battery or BatteryMonitor()
    thresholds = thresholds_from_env()
    if notifier is None and from_config:
        notifier = notifier_from_env()
    # El vigilante solo corre al arrancar desde la configuración real
    watch = from_config if battery_watch is None else battery_watch
    watcher = BatteryWatcher(thresholds, notifier)

    async def watch_battery() -> None:
        while True:
            try:
                reading = await asyncio.to_thread(battery_monitor.read)
                alerts = watcher.evaluate(reading)
                if notifier is not None:
                    for alert in alerts:
                        await asyncio.to_thread(notifier.send, alert)
            except BatteryError:
                pass  # se reintenta en el siguiente ciclo
            await asyncio.sleep(BATTERY_WATCH_EVERY_S)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):
        task = asyncio.create_task(watch_battery()) if watch else None
        try:
            yield
        finally:
            fade.shutdown()
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(title="selfRoomHub", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        result = {"status": "ok"}
        if bt_targets:
            result["bluetooth"] = "ok" if bluetooth_available() else "unavailable"
        return result

    @app.get("/battery", dependencies=[Depends(auth)])
    def read_battery() -> dict[str, object]:
        try:
            reading = battery_monitor.read()
        except BatteryError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
        return {**reading, "advice": advice(reading, thresholds)}

    @app.post("/battery/test-alert", dependencies=[Depends(auth)])
    def battery_test_alert() -> dict[str, str]:
        if notifier is None:
            raise HTTPException(
                status_code=409,
                detail="Avisos externos desactivados: falta SELFROOMHUB_NTFY_TOPIC",
            )
        test = Alert(
            "test",
            "Prueba de avisos",
            "Si ves esto, los avisos de batería funcionan.",
            "default",
            ["white_check_mark"],
        )
        if not notifier.send(test):
            raise HTTPException(status_code=502, detail="No se pudo enviar el aviso")
        return {"status": "sent"}

    @app.get("/devices", dependencies=[Depends(auth)])
    def list_devices() -> list[dict[str, object]]:
        return [_state(d) for d in registry.values()]

    @app.get("/devices/{device_id}", dependencies=[Depends(auth)])
    def read_device(device_id: str) -> dict[str, object]:
        return _state(get_device(device_id))

    @app.post("/devices/{device_id}/power", dependencies=[Depends(auth)])
    def set_power(device_id: str, body: PowerRequest, hard: bool = False) -> dict[str, object]:
        device = get_device(device_id)
        try:
            if body.on:
                device.on()
            else:
                soft.off(device, hard=hard)
        except DeviceError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
        return _state(device)

    @app.post("/devices/{device_id}/toggle", dependencies=[Depends(auth)])
    def toggle(device_id: str) -> dict[str, object]:
        device = get_device(device_id)
        st = device.status()
        if not st.online:
            raise HTTPException(status_code=503, detail=f"{device_id} está fuera de línea")
        try:
            if st.on:
                soft.off(device)
            else:
                device.on()
        except DeviceError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
        return _state(device)

    @app.post("/devices/{device_id}/timer", dependencies=[Depends(auth)])
    def set_timer(device_id: str, body: TimerRequest) -> dict[str, object]:
        device = get_device(device_id)
        try:
            soft.set_timer(device, body.minutes)
        except NotImplementedError as e:
            raise HTTPException(status_code=501, detail=str(e)) from e
        except DeviceError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
        return {"id": device.id, "minutes": body.minutes}

    @app.get("/mode", dependencies=[Depends(auth)])
    def read_mode() -> dict[str, str]:
        return mode_state.current()

    @app.put("/mode", dependencies=[Depends(auth)])
    def put_mode(body: ModeRequest) -> dict[str, str]:
        mode_state.set(body.mode)
        return mode_state.current()

    @app.get("/bluetooth", dependencies=[Depends(auth)])
    def list_bluetooth() -> list[dict[str, object]]:
        return [bt_state(t) for t in bt_targets.values()]

    @app.post("/bluetooth/{target_id}/connect", dependencies=[Depends(auth)])
    def bt_connect(target_id: str) -> dict[str, object]:
        target = get_target(target_id)
        try:
            bt.connect(target.address)
        except BluetoothError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
        wait_connected(target, True)
        return bt_state(target, strict=True)

    @app.post("/bluetooth/{target_id}/disconnect", dependencies=[Depends(auth)])
    def bt_disconnect(target_id: str) -> dict[str, object]:
        target = get_target(target_id)
        try:
            bt.disconnect(target.address)
        except BluetoothError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
        wait_connected(target, False)
        return bt_state(target, strict=True)

    @app.get("/scenes", dependencies=[Depends(auth)])
    def list_scenes() -> list[dict[str, object]]:
        return [{"name": n, "steps": len(s)} for n, s in scene_defs.items()]

    # def: los pasos tienen esperas y corren en el threadpool
    # Último resultado de escena: el panel lo muestra (para saber si un sticker funcionó)
    last_event: dict[str, object] = {"id": 0, "event": None}
    events_lock = threading.Lock()

    def summarize(name: str, results: list[dict[str, object]]) -> str:
        title = name.replace("_", " ").replace("-", " ").capitalize()
        failed = next((r for r in results if not r["ok"]), None)
        if failed is None:
            return f"{title} ✓"
        detail = str(failed.get("detail") or "")[:80]
        return f"{title}: falló {failed['step']}" + (f" ({detail})" if detail else "")

    def finish_scene(
        name: str, results: list[dict[str, object]], **extra: object
    ) -> dict[str, object]:
        ok = all(r["ok"] for r in results)
        summary = summarize(name, results)
        with events_lock:
            last_event["id"] = int(last_event["id"]) + 1  # type: ignore[call-overload]
            last_event["event"] = {
                "id": last_event["id"],
                "name": name,
                "ok": ok,
                "summary": summary,
                "at": datetime.now().astimezone().isoformat(timespec="seconds"),
                **extra,
            }
        # Aviso al teléfono (ntfy): para saber si un sticker o "Hey Siri" funcionó
        if notifier is not None:
            done = sum(1 for r in results if r["ok"])
            alert = Alert(
                kind="scene",
                title=summary,
                message=f"{done} de {len(results)} pasos completados.",
                priority="default" if ok else "high",
                tags=["white_check_mark"] if ok else ["warning"],
            )
            threading.Thread(target=notifier.send, args=(alert,), daemon=True).start()
        return {"name": name, "ok": ok, "summary": summary, "steps": results, **extra}

    @app.get("/scenes/last", dependencies=[Depends(auth)])
    def last_scene() -> dict[str, object] | None:
        return last_event["event"]  # type: ignore[return-value]

    @app.post("/scenes/{name}", dependencies=[Depends(auth)])
    def post_scene(name: str) -> dict[str, object]:
        steps = scene_defs.get(name)
        if steps is None:
            raise HTTPException(status_code=404, detail=f"Escena no encontrada: {name}")
        return finish_scene(name, run_scene(steps, scene_ctx))

    @app.get("/routines", dependencies=[Depends(auth)])
    def list_routines() -> list[dict[str, object]]:
        return [{"name": n, "windows": [w.to_json() for w in ws]} for n, ws in routine_defs.items()]

    @app.post("/routines/{name}", dependencies=[Depends(auth)])
    def post_routine(name: str) -> dict[str, object]:
        windows = routine_defs.get(name)
        if windows is None:
            raise HTTPException(status_code=404, detail=f"Rutina no encontrada: {name}")
        now = clock()
        window = next((w for w in windows if w.contains(now.time())), None)
        if window is None:
            raise HTTPException(status_code=409, detail=f"Ninguna escena aplica a las {now:%H:%M}")
        results = run_scene(scene_defs[window.scene], scene_ctx)
        return finish_scene(window.scene, results, routine=name, scene=window.scene)

    def spotify_http_error(e: SpotifyError) -> HTTPException:
        code = e.status if e.status in (404, 409, 422) else 502
        return HTTPException(status_code=code, detail=e.message)

    # El navegador no manda el header: el token del backend viaja por query
    @app.get("/spotify/login", include_in_schema=False)
    def spotify_login(token: str = "") -> RedirectResponse:
        if not secrets.compare_digest(token.encode(), expected.encode()):
            raise HTTPException(status_code=401, detail="No autorizado")
        try:
            return RedirectResponse(sp.login_url())
        except SpotifyError as e:
            raise spotify_http_error(e) from e

    # Sin auth: lo protege el state de un solo uso
    @app.get("/spotify/callback", include_in_schema=False)
    def spotify_callback(code: str = "", state: str = "", error: str = "") -> HTMLResponse:
        try:
            if error or not code:
                raise SpotifyError(400, f"Spotify rechazó el vínculo: {error or 'sin código'}")
            sp.handle_callback(code, state)
        except SpotifyError as e:
            page = f"<h1>No se pudo vincular Spotify</h1><p>{html.escape(e.message)}</p>"
            return HTMLResponse(_page(page), status_code=e.status if e.status < 500 else 502)
        return HTMLResponse(_page("<h1>Spotify vinculado. Ya puedes cerrar esta pestaña.</h1>"))

    @app.get("/spotify/status", dependencies=[Depends(auth)])
    def spotify_status() -> dict[str, object]:
        result: dict[str, object] = {
            "configured": sp.configured,
            "linked": sp.linked,
            "devices": None,
        }
        if result["linked"]:
            try:
                result["devices"] = [
                    {
                        "name": d.get("name"),
                        "type": d.get("type"),
                        "active": bool(d.get("is_active")),
                    }
                    for d in sp.devices()
                ]
            except SpotifyError as e:
                result["error"] = e.message
        return result

    @app.post("/spotify/play", dependencies=[Depends(auth)])
    def spotify_play(body: SpotifyPlayRequest) -> dict[str, object]:
        if not body.query and not body.uri:
            raise HTTPException(status_code=422, detail="Falta query o uri")
        try:
            return sp.play(body.query, body.uri, body.type, body.device, body.shuffle)
        except SpotifyError as e:
            raise spotify_http_error(e) from e

    @app.get("/now-playing", dependencies=[Depends(auth)])
    def read_now_playing() -> dict[str, object]:
        return now_playing.to_json()

    @app.put("/now-playing", dependencies=[Depends(auth)])
    def put_now_playing(body: NowPlayingUpdate) -> dict[str, object]:
        try:
            now_playing.update(body)
        except ArtError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        return now_playing.to_json()

    # def: la consulta a LRCLIB bloquea y corre en el threadpool
    @app.get("/lyrics", dependencies=[Depends(auth)])
    def read_lyrics() -> dict[str, object]:
        title = now_playing.title
        if not title:
            raise HTTPException(status_code=404, detail=NO_LYRICS)
        artist = now_playing.artist
        try:
            found = lyrics.lookup(title, artist, now_playing.album, now_playing.duration_ms)
        except LyricsUnavailable as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
        if found is None:
            raise HTTPException(status_code=404, detail=NO_LYRICS)
        return {"title": title, "artist": artist, **found, "source": "lrclib"}

    # async: el long-poll no ocupa hilos y la cola se toca solo desde el loop
    @app.post("/media/command", status_code=202, dependencies=[Depends(auth)])
    async def post_media_command(body: MediaCommand) -> dict[str, int]:
        return {"id": media_queue.add(body)}

    @app.get("/media/commands", dependencies=[Depends(auth)])
    async def get_media_commands(after: int = 0, wait: float = 0) -> list[dict[str, object]]:
        found = await media_queue.wait_after(after, min(max(wait, 0), MAX_WAIT_S))
        return [c.to_json() for c in found]

    # La URL de la portada lleva versión (?v=), por eso se puede cachear un día
    @app.get("/now-playing/art")
    def now_playing_art() -> Response:
        if now_playing.art is None or now_playing.art_type is None:
            raise HTTPException(status_code=404, detail="Sin portada")
        return Response(
            content=now_playing.art,
            media_type=now_playing.art_type,
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @app.get("/panel", include_in_schema=False)
    def panel_redirect() -> RedirectResponse:
        return RedirectResponse("/panel/")

    app.mount("/panel", PanelFiles(directory=PANEL_DIR, html=True), name="panel")

    return app
