import asyncio
from types import SimpleNamespace

import pytest
from kasa import KasaException, Module

from app.devices.base import DeviceError
from app.devices.tapo import TapoDevice


class FakeLight:
    """Imita el módulo Light de python-kasa en un foco con temperatura y color."""

    def __init__(self, features=("brightness", "color_temp", "hsv")):
        self.features = set(features)
        self.brightness = 80
        self.color_temp = 2700
        self.hsv = SimpleNamespace(hue=0, saturation=0, value=80)
        self.valid_temperature_range = SimpleNamespace(min=2500, max=6500)
        self.states = []

    def has_feature(self, name):
        return name in self.features

    async def set_state(self, state):
        self.states.append(state)


class FakeKasa:
    def __init__(self, light=None, fail_times=0, error=None):
        self.is_on = False
        self.light = light
        self.modules = {Module.Light: light} if light else {}
        self.fail_times = fail_times
        self.error = error or KasaException("caído")
        self.calls = []
        self.disconnected = False

    def _maybe_fail(self):
        if self.fail_times:
            self.fail_times -= 1
            raise self.error

    async def update(self):
        self.calls.append("update")
        self._maybe_fail()

    async def turn_on(self):
        self.calls.append("on")
        self._maybe_fail()
        self.is_on = True

    async def turn_off(self):
        self.calls.append("off")
        self._maybe_fail()
        self.is_on = False

    async def disconnect(self):
        self.disconnected = True


def make(*devs, **kw):
    """Cada conexión entrega el siguiente doble; cuenta cuántas veces se conectó."""
    queue = list(devs)
    connects = []

    async def connect():
        connects.append(1)
        if not queue:
            raise KasaException("no responde")
        return queue.pop(0)

    d = TapoDevice("foco", "Foco", "1.2.3.4", "user", "pass", connect=connect, **kw)
    return d, connects


def test_on_off_y_reusa_conexion():
    k = FakeKasa()
    d, connects = make(k)
    d.on()
    assert d.status().on is True
    d.off()
    assert d.status().on is False
    assert len(connects) == 1
    assert k.calls == ["on", "update", "off", "update"]


def test_reconecta_tras_un_fallo():
    roto = FakeKasa(fail_times=1)
    sano = FakeKasa()
    d, connects = make(roto, sano)
    d.on()
    assert roto.disconnected and sano.is_on
    assert len(connects) == 2


def test_error_persistente_es_device_error():
    d, _ = make(FakeKasa(fail_times=5))
    with pytest.raises(DeviceError):
        d.on()


def test_oserror_tambien_es_device_error():
    d, _ = make(FakeKasa(fail_times=5, error=OSError("sin ruta")))
    with pytest.raises(DeviceError):
        d.off()


def test_status_offline_si_no_conecta():
    d, _ = make()
    st = d.status()
    assert (st.online, st.on, st.light) == (False, None, None)


def test_status_luz_en_temperatura():
    d, _ = make(FakeKasa(FakeLight()))
    light = d.status().light
    assert light.brightness == 80
    assert light.color_temp == 2700
    assert (light.hue, light.saturation) == (None, None)
    assert light.color_temp_range == (2500, 6500)
    assert light.color is True


def test_status_luz_en_color():
    fl = FakeLight()
    fl.color_temp = 0  # Tapo informa 0 cuando está en modo color
    fl.hsv = SimpleNamespace(hue=240, saturation=90, value=50)
    d, _ = make(FakeKasa(fl))
    light = d.status().light
    assert light.color_temp is None
    assert (light.hue, light.saturation) == (240, 90)


def test_status_sin_modulo_de_luz():
    d, _ = make(FakeKasa())
    assert d.status().light is None


def test_set_light_temperatura():
    fl = FakeLight()
    d, _ = make(FakeKasa(fl))
    d.set_light(brightness=30, color_temp=2700)
    s = fl.states[-1]
    assert (s.light_on, s.brightness, s.color_temp, s.hue) == (True, 30, 2700, None)


def test_set_light_color_pone_temp_en_cero():
    fl = FakeLight()
    d, _ = make(FakeKasa(fl))
    d.set_light(hue=200, saturation=100)
    s = fl.states[-1]
    assert (s.hue, s.saturation, s.color_temp, s.brightness) == (200, 100, 0, None)


def test_set_light_fuera_de_rango():
    d, _ = make(FakeKasa(FakeLight()))
    with pytest.raises(ValueError, match="2500"):
        d.set_light(color_temp=9000)


def test_set_light_sin_soporte_de_color():
    d, _ = make(FakeKasa(FakeLight(features=("brightness", "color_temp"))))
    with pytest.raises(ValueError, match="color"):
        d.set_light(hue=10, saturation=10)


def test_set_light_en_enchufe_no_implementado():
    d, _ = make(FakeKasa())
    with pytest.raises(NotImplementedError):
        d.set_light(brightness=50)


def test_timeout_es_device_error():
    class Lento(FakeKasa):
        async def turn_on(self):
            await asyncio.sleep(5)

    d, _ = make(Lento(), timeout=0.05)
    with pytest.raises(DeviceError, match="sin respuesta"):
        d.on()
