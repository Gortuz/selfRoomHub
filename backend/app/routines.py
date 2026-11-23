"""Rutinas: ventanas horarias que eligen qué escena ejecutar."""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import time
from typing import Any

from app.mode import in_window, parse_hhmm
from app.scenes import NAME_RE, SceneError


@dataclass(frozen=True)
class Window:
    start: time
    end: time
    scene: str

    def contains(self, now: time) -> bool:
        return in_window(self.start, self.end, now)

    def to_json(self) -> dict[str, str]:
        return {
            "from": self.start.strftime("%H:%M"),
            "to": self.end.strftime("%H:%M"),
            "scene": self.scene,
        }


def _parse_window(raw: Any, scene_names: Collection[str]) -> Window:
    if not isinstance(raw, dict):
        raise SceneError("cada ventana debe ser un dict {from, to, scene}")
    try:
        start, end = parse_hhmm(raw.get("from")), parse_hhmm(raw.get("to"))
    except ValueError as e:
        raise SceneError(str(e)) from e
    if start == end:
        raise SceneError("from y to no pueden ser iguales")
    scene = raw.get("scene")
    if not isinstance(scene, str) or scene not in scene_names:
        raise SceneError(f"escena inexistente {scene!r}")
    return Window(start, end, scene)


def parse_routines(raw: Any, scene_names: Collection[str]) -> dict[str, list[Window]]:
    """Valida la sección `routines`; lanza SceneError con la rutina y la ventana."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise SceneError("routines debe ser un dict nombre -> lista de ventanas")
    routines: dict[str, list[Window]] = {}
    for name, raw_windows in raw.items():
        if not isinstance(name, str) or not NAME_RE.match(name):
            raise SceneError(f"Nombre de rutina inválido: {name!r} (usa a-z, 0-9, _ y -)")
        if not isinstance(raw_windows, list):
            raise SceneError(f"Rutina {name}: debe ser una lista de ventanas")
        windows = []
        for i, raw_window in enumerate(raw_windows, 1):
            try:
                windows.append(_parse_window(raw_window, scene_names))
            except SceneError as e:
                raise SceneError(f"Rutina {name}, ventana {i}: {e}") from e
        routines[name] = windows
    return routines
