"""Avisos de batería del servidor (se carga a mano): umbrales, estado y envío a ntfy."""

import base64
import logging
import os
import time
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

log = logging.getLogger(__name__)

Advice = Literal["critical", "connect", "disconnect"]
HYSTERESIS = 5
CRITICAL_EVERY_S = 15 * 60
SEND_TIMEOUT_S = 10
DEFAULT_NTFY_URL = "https://ntfy.sh"


@dataclass(frozen=True)
class Thresholds:
    low: int = 25
    high: int = 80
    critical: int = 15


@dataclass(frozen=True)
class Alert:
    kind: str
    title: str
    message: str
    priority: str = "default"
    tags: list[str] = field(default_factory=list)


class Notifier(Protocol):
    def send(self, alert: Alert) -> bool: ...


def _env_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{name} debe ser un entero, no {raw!r}") from None


def thresholds_from_env(env: Mapping[str, str] | None = None) -> Thresholds:
    env = os.environ if env is None else env
    t = Thresholds(
        low=_env_int(env, "SELFROOMHUB_BATTERY_LOW", 25),
        high=_env_int(env, "SELFROOMHUB_BATTERY_HIGH", 80),
        critical=_env_int(env, "SELFROOMHUB_BATTERY_CRITICAL", 15),
    )
    if not 0 < t.critical < t.low < t.high <= 100:
        raise ValueError(
            "Umbrales de batería inválidos: se requiere 0 < critical < low < high <= 100 "
            f"(critical={t.critical}, low={t.low}, high={t.high})"
        )
    return t


def advice(battery: Mapping[str, Any], t: Thresholds) -> Advice | None:
    pct, charging = battery["percentage"], battery["charging"]
    if not charging and pct <= t.critical:
        return "critical"
    if not charging and pct <= t.low:
        return "connect"
    if charging and pct >= t.high:
        return "disconnect"
    return None


class BatteryWatcher:
    """Un aviso por cruce de umbral; el crítico se repite mientras siga igual."""

    def __init__(
        self,
        thresholds: Thresholds,
        notifier: Notifier | None = None,
        clock: Callable[[], float] = time.monotonic,
        critical_every: float = CRITICAL_EVERY_S,
    ) -> None:
        self.thresholds = thresholds
        self.notifier = notifier
        self._clock = clock
        self._critical_every = critical_every
        self._connect_sent = False
        self._disconnect_sent = False
        self._critical_at: float | None = None

    def evaluate(self, battery: Mapping[str, Any]) -> list[Alert]:
        t = self.thresholds
        pct, charging = battery["percentage"], battery["charging"]
        # Rearme con histéresis
        if charging or pct > t.low + HYSTERESIS:
            self._connect_sent = False
        if not charging or pct < t.high - HYSTERESIS:
            self._disconnect_sent = False
        if charging or pct > t.critical:
            self._critical_at = None

        now = self._clock()
        match advice(battery, t):
            case "critical":
                # Al entrar en crítico no se manda además "connect"
                self._connect_sent = True
                if self._critical_at is None or now - self._critical_at >= self._critical_every:
                    self._critical_at = now
                    return [
                        Alert(
                            "critical",
                            "Batería crítica",
                            f"Queda {pct} % y no está cargando. "
                            "Si se apaga, el cuarto deja de responder.",
                            "urgent",
                            ["rotating_light", "battery"],
                        )
                    ]
            case "connect" if not self._connect_sent:
                self._connect_sent = True
                return [
                    Alert(
                        "connect",
                        "Conecta el cargador",
                        f"La batería del servidor está al {pct} %.",
                        "high",
                        ["warning", "battery"],
                    )
                ]
            case "disconnect" if not self._disconnect_sent:
                self._disconnect_sent = True
                return [
                    Alert(
                        "disconnect",
                        "Ya puedes desconectar el cargador",
                        f"La batería llegó al {pct} %. "
                        f"Mantenerla entre {t.low} y {t.high} % alarga su vida.",
                        "default",
                        ["electric_plug", "battery"],
                    )
                ]
        return []


class NtfyNotifier:
    def __init__(
        self,
        url: str,
        topic: str,
        token: str | None = None,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self.url = url.rstrip("/")
        self.topic = topic
        self.token = token
        self._open = opener

    def send(self, alert: Alert) -> bool:
        # El título va en RFC 2047 para admitir acentos en el header
        title = base64.b64encode(alert.title.encode()).decode()
        headers = {
            "Title": f"=?UTF-8?B?{title}?=",
            "Priority": alert.priority,
            "Tags": ",".join(alert.tags),
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(
            f"{self.url}/{self.topic}",
            data=alert.message.encode(),
            headers=headers,
            method="POST",
        )
        try:
            with self._open(req, timeout=SEND_TIMEOUT_S):
                return True
        except (OSError, ValueError) as e:
            log.warning("No se pudo enviar el aviso a ntfy: %s", e)
            return False


def notifier_from_env(env: Mapping[str, str] | None = None) -> NtfyNotifier | None:
    env = os.environ if env is None else env
    topic = env.get("SELFROOMHUB_NTFY_TOPIC", "").strip()
    if not topic:
        return None
    return NtfyNotifier(
        env.get("SELFROOMHUB_NTFY_URL", "").strip() or DEFAULT_NTFY_URL,
        topic,
        env.get("SELFROOMHUB_NTFY_TOKEN", "").strip() or None,
    )
