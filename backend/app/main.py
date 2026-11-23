"""API FastAPI de selfRoomHub.

Arranque:
    uv run uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
"""

import secrets
import time
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import RedirectResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import config
from app.bluetooth import BluetoothController, BluetoothError, BluetoothTarget
from app.devices.base import Device, DeviceError
from app.now_playing import ArtError, NowPlaying, NowPlayingUpdate

BT_WAIT_POLLS = 8
HEALTH_CACHE_S = 60
PANEL_DIR = Path(__file__).parent / "panel"


class PowerRequest(BaseModel):
    on: bool


def _state(device: Device) -> dict[str, object]:
    st = device.status()
    return {"id": device.id, "name": device.name, "online": st.online, "on": st.on}


class PanelFiles(StaticFiles):
    """Archivos del panel sin caché fija: el kiosco ve cada cambio (revalida con ETag)."""

    async def get_response(self, path: str, scope):  # type: ignore[override]
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def create_app(
    devices: dict[str, Device] | None = None,
    token: str | None = None,
    bluetooth_targets: dict[str, BluetoothTarget] | None = None,
    bluetooth_controller: BluetoothController | None = None,
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

    app = FastAPI(title="selfRoomHub")

    @app.get("/health")
    def health() -> dict[str, str]:
        result = {"status": "ok"}
        if bt_targets:
            result["bluetooth"] = "ok" if bluetooth_available() else "unavailable"
        return result

    @app.get("/devices", dependencies=[Depends(auth)])
    def list_devices() -> list[dict[str, object]]:
        return [_state(d) for d in registry.values()]

    @app.get("/devices/{device_id}", dependencies=[Depends(auth)])
    def read_device(device_id: str) -> dict[str, object]:
        return _state(get_device(device_id))

    @app.post("/devices/{device_id}/power", dependencies=[Depends(auth)])
    def set_power(device_id: str, body: PowerRequest) -> dict[str, object]:
        device = get_device(device_id)
        try:
            device.on() if body.on else device.off()
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
            device.off() if st.on else device.on()
        except DeviceError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
        return _state(device)

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
