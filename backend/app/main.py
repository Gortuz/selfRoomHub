"""API FastAPI de selfRoomHub.

Arranque:
    uv run uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
"""

import secrets
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app import config
from app.devices.base import Device, DeviceError


class PowerRequest(BaseModel):
    on: bool


def _state(device: Device) -> dict[str, object]:
    st = device.status()
    return {"id": device.id, "name": device.name, "online": st.online, "on": st.on}


def create_app(devices: dict[str, Device] | None = None, token: str | None = None) -> FastAPI:
    if devices is None or token is None:
        config.load_env()
        if token is None:
            token = config.get_token()
        if devices is None:
            devices = config.load_devices(config.get_config_path())
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

    app = FastAPI(title="selfRoomHub")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

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

    return app
