"""Escenas: listas de pasos definidas en config/devices.yaml.

`run_scene` es síncrono (tiene esperas): el endpoint corre en el threadpool.
Encolar órdenes de media desde ese hilo es seguro porque `CommandQueue.add`
usa un lock y despierta a los esperadores con `call_soon_threadsafe`.
"""

import re
import time
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.bluetooth import BluetoothController, BluetoothError, BluetoothTarget
from app.devices.base import Device, DeviceError
from app.media import CommandQueue, MediaCommand
from app.mode import ModeState
from app.soft_off import SoftPower
from app.spotify import DeviceNotFound, SpotifyClient, SpotifyError

NAME_RE = re.compile(r"^[a-z0-9_-]+$")
STEP_KINDS = ("power", "toggle", "bluetooth", "media", "spotify", "wake", "wait", "timer", "mode")
MODE_VALUES = ("night", "day", "auto")
MAX_TIMER_MIN = 720
SPOTIFY_TYPES = ("artist", "album", "playlist", "track")
SPOTIFY_WAKE_WAIT_S = 3
MAX_WAIT_S = 30
BT_WAIT_POLLS = 8


class SceneError(ValueError):
    """Escena mal definida en la configuración."""


@dataclass(frozen=True)
class Step:
    kind: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class SceneContext:
    devices: dict[str, Device]
    bluetooth: BluetoothController
    bt_targets: dict[str, BluetoothTarget]
    queue: CommandQueue
    sleep: Callable[[float], None] = time.sleep
    spotify: SpotifyClient | None = None
    mode: ModeState = field(default_factory=ModeState)
    power: SoftPower | None = None  # apagado suave de audio; sin él se apaga directo


def _ids(valid: Collection[str]) -> str:
    return ", ".join(sorted(valid)) or "(ninguno)"


def _parse_step(raw: Any, devices: Collection[str], bt_ids: Collection[str]) -> Step:
    # Un paso sin parámetros puede escribirse solo con su nombre: `- wake`
    if raw == "wake":
        return Step("wake")
    if not isinstance(raw, dict) or len(raw) != 1:
        raise SceneError("cada paso debe ser un dict con una sola clave")
    kind, body = next(iter(raw.items()))
    if kind not in STEP_KINDS:
        raise SceneError(f"paso desconocido {kind!r} (válidos: {', '.join(STEP_KINDS)})")
    if kind == "wake":
        return Step("wake")
    if kind == "wait":
        if isinstance(body, bool) or not isinstance(body, int | float):
            raise SceneError("wait exige un número de segundos")
        if not 0 <= body <= MAX_WAIT_S:
            raise SceneError(f"wait debe estar entre 0 y {MAX_WAIT_S} segundos")
        return Step("wait", {"seconds": body})
    if kind == "mode":
        if body not in MODE_VALUES:
            raise SceneError(f"mode debe ser uno de: {', '.join(MODE_VALUES)}")
        return Step("mode", {"mode": body})
    if not isinstance(body, dict):
        raise SceneError(f"{kind} exige un dict de parámetros")
    # YAML 1.1 lee la clave `on` (sin comillas) como el booleano True
    if True in body and "on" not in body:
        body = {("on" if k is True else k): v for k, v in body.items()}
    if kind in ("power", "toggle"):
        device = body.get("device")
        if not isinstance(device, str):
            raise SceneError(f"{kind} exige device")
        if device not in devices:
            raise SceneError(f"dispositivo inexistente {device!r} (válidos: {_ids(devices)})")
        if kind == "toggle":
            return Step("toggle", {"device": device})
        if not isinstance(body.get("on"), bool):
            raise SceneError("power exige on true/false")
        return Step("power", {"device": device, "on": body["on"]})
    if kind == "timer":
        device, minutes = body.get("device"), body.get("minutes")
        if not isinstance(device, str):
            raise SceneError("timer exige device")
        if device not in devices:
            raise SceneError(f"dispositivo inexistente {device!r} (válidos: {_ids(devices)})")
        if isinstance(minutes, bool) or not isinstance(minutes, int):
            raise SceneError("timer exige minutes (entero)")
        if not 0 <= minutes <= MAX_TIMER_MIN:
            raise SceneError(f"timer minutes debe estar entre 0 y {MAX_TIMER_MIN}")
        return Step("timer", {"device": device, "minutes": minutes})
    if kind == "bluetooth":
        target = body.get("id")
        if not isinstance(target, str):
            raise SceneError("bluetooth exige id")
        if target not in bt_ids:
            raise SceneError(f"bluetooth inexistente {target!r} (válidos: {_ids(bt_ids)})")
        if not isinstance(body.get("connect"), bool):
            raise SceneError("bluetooth exige connect true/false")
        return Step("bluetooth", {"id": target, "connect": body["connect"]})
    if kind == "spotify":
        return _parse_spotify(body)
    try:
        return Step("media", {"command": MediaCommand(**body)})
    except (ValidationError, TypeError) as e:
        raise SceneError(f"media inválido: {e}") from e


def _parse_spotify(body: dict[str, Any]) -> Step:
    play, uri = body.get("play"), body.get("uri")
    if not (isinstance(play, str) and play.strip()) and not (isinstance(uri, str) and uri):
        raise SceneError("spotify exige play (texto) o uri")
    kind = body.get("type", "artist")
    if kind not in SPOTIFY_TYPES:
        raise SceneError(f"spotify type inválido {kind!r} (válidos: {', '.join(SPOTIFY_TYPES)})")
    device, shuffle = body.get("device"), body.get("shuffle")
    if device is not None and not isinstance(device, str):
        raise SceneError("spotify device debe ser texto")
    if shuffle is not None and not isinstance(shuffle, bool):
        raise SceneError("spotify shuffle debe ser true/false")
    args = {"query": play or None, "uri": uri or None, "type": kind}
    args.update(device=device, shuffle=shuffle)
    return Step("spotify", args)


def parse_scenes(
    raw: Any, device_ids: Collection[str], bt_ids: Collection[str]
) -> dict[str, list[Step]]:
    """Valida la sección `scenes` completa; lanza SceneError con la escena y el paso."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise SceneError("scenes debe ser un dict nombre -> lista de pasos")
    scenes: dict[str, list[Step]] = {}
    for name, raw_steps in raw.items():
        if not isinstance(name, str) or not NAME_RE.match(name):
            raise SceneError(f"Nombre de escena inválido: {name!r} (usa a-z, 0-9, _ y -)")
        if not isinstance(raw_steps, list):
            raise SceneError(f"Escena {name}: debe ser una lista de pasos")
        steps = []
        for i, raw_step in enumerate(raw_steps, 1):
            try:
                steps.append(_parse_step(raw_step, device_ids, bt_ids))
            except SceneError as e:
                raise SceneError(f"Escena {name}, paso {i}: {e}") from e
        scenes[name] = steps
    return scenes


def _wait_bt(ctx: SceneContext, target: BluetoothTarget, expected: bool) -> bool:
    for _ in range(BT_WAIT_POLLS):
        try:
            if ctx.bluetooth.is_connected(target.address) == expected:
                return True
        except BluetoothError:
            pass
        ctx.sleep(1)
    return False


def _spotify_step(args: dict[str, Any], ctx: SceneContext) -> str:
    if ctx.spotify is None:
        raise SceneError("Spotify no configurado")
    try:
        try:
            result = ctx.spotify.play(**args)
        except DeviceNotFound:
            # Spotify cerrado o dormido en el teléfono: se despierta y se reintenta una vez
            ctx.queue.add(MediaCommand(action="wake"))
            ctx.sleep(SPOTIFY_WAKE_WAIT_S)
            result = ctx.spotify.play(**args)
    except SpotifyError as e:
        raise SceneError(e.message) from e
    return f"reproduciendo {result['uri']} en {result['device']}"


def _off(device: Device, ctx: SceneContext) -> None:
    if ctx.power is not None:
        ctx.power.off(device)
    else:
        device.off()


def _do_step(step: Step, ctx: SceneContext) -> str:
    """Ejecuta un paso y devuelve el detalle; lanza SceneError si falla."""
    a = step.args
    if step.kind == "power":
        device = ctx.devices[a["device"]]
        if a["on"]:
            device.on()
        else:
            _off(device, ctx)
        return f"{device.id} {'encendido' if a['on'] else 'apagado'}"
    if step.kind == "toggle":
        device = ctx.devices[a["device"]]
        st = device.status()
        if not st.online:
            raise SceneError(f"{device.id} está fuera de línea")
        if st.on:
            _off(device, ctx)
        else:
            device.on()
        return f"{device.id} {'apagado' if st.on else 'encendido'}"
    if step.kind == "timer":
        device = ctx.devices[a["device"]]
        try:
            if ctx.power is not None:
                ctx.power.set_timer(device, a["minutes"])
            else:
                device.set_timer(a["minutes"] * 60)
        except NotImplementedError as e:
            raise SceneError(f"{device.id} no tiene temporizador") from e
        if a["minutes"] == 0:
            return f"temporizador de {device.id} cancelado"
        return f"{device.id} se apagará en {a['minutes']} min"
    if step.kind == "mode":
        ctx.mode.set(a["mode"])
        return f"modo {a['mode']}"
    if step.kind == "bluetooth":
        target = ctx.bt_targets[a["id"]]
        word = "conectado" if a["connect"] else "desconectado"
        try:
            already = ctx.bluetooth.is_connected(target.address)
        except BluetoothError:
            already = None
        if already == a["connect"]:
            return f"{target.id} ya {word}"
        if a["connect"]:
            ctx.bluetooth.connect(target.address)
        else:
            ctx.bluetooth.disconnect(target.address)
        if not _wait_bt(ctx, target, a["connect"]):
            raise SceneError(f"{target.id} no quedó {word}")
        return f"{target.id} {word}"
    if step.kind == "media":
        command: MediaCommand = a["command"]
        return f"orden {command.action} encolada (id {ctx.queue.add(command)})"
    if step.kind == "spotify":
        return _spotify_step(a, ctx)
    if step.kind == "wake":
        return f"orden wake encolada (id {ctx.queue.add(MediaCommand(action='wake'))})"
    ctx.sleep(a["seconds"])
    return f"esperó {a['seconds']} s"


def run_scene(steps: list[Step], ctx: SceneContext) -> list[dict[str, object]]:
    """Ejecuta los pasos en orden; un fallo se registra y no detiene los siguientes."""
    results: list[dict[str, object]] = []
    for step in steps:
        try:
            detail, ok = _do_step(step, ctx), True
        except (DeviceError, BluetoothError, SceneError) as e:
            detail, ok = str(e), False
        results.append({"step": step.kind, "ok": ok, "detail": detail})
    return results
