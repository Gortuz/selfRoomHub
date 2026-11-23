import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.devices.base import DeviceError
from app.devices.tuya import TuyaDevice


class FakeClient:
    def __init__(self, status_result=None, error=None):
        self.calls = []
        self.status_result = status_result
        self.error = error

    def turn_on(self, switch=1):
        self.calls.append(("on", switch))
        return self.error or {"dps": {str(switch): True}}

    def turn_off(self, switch=1):
        self.calls.append(("off", switch))
        return self.error or {"dps": {str(switch): False}}

    def status(self):
        return self.error or self.status_result


def make(client, switch_dp=1):
    return TuyaDevice("t", "T", "devid", "1.2.3.4", "key", switch_dp=switch_dp, client=client)


def test_on_off_switch():
    c = FakeClient()
    d = make(c, switch_dp=2)
    d.on()
    d.off()
    assert c.calls == [("on", 2), ("off", 2)]


def test_error_a_device_error():
    d = make(FakeClient(error={"Error": "Network Error", "Err": "901"}))
    with pytest.raises(DeviceError):
        d.on()
    with pytest.raises(DeviceError):
        d.off()


def test_status_error_offline():
    st = make(FakeClient(error={"Error": "x"})).status()
    assert (st.online, st.on) == (False, None)


def test_status_lee_dp():
    st = make(FakeClient(status_result={"dps": {"1": True}})).status()
    assert (st.online, st.on) == (True, True)
    st = make(FakeClient(status_result={"dps": {"3": 5}}), switch_dp=3).status()
    assert st.on is True


class SlowClient(FakeClient):
    """Detecta si dos llamadas se solapan en el mismo cliente."""

    def __init__(self):
        super().__init__(status_result={"dps": {"1": True}})
        self.active = 0
        self.overlap = False

    def _enter(self):
        self.active += 1
        if self.active > 1:
            self.overlap = True
        time.sleep(0.01)
        self.active -= 1

    def turn_on(self, switch=1):
        self._enter()
        return super().turn_on(switch)

    def status(self):
        self._enter()
        return super().status()


def test_llamadas_concurrentes_no_se_solapan():
    c = SlowClient()
    d = make(c)
    with ThreadPoolExecutor(max_workers=8) as pool:
        for i in range(16):
            pool.submit(d.on if i % 2 else d.status)
    assert not c.overlap


# --- temporizador


class TimerClient(FakeClient):
    def set_value(self, index, value):
        self.calls.append(("set_value", index, value))
        return self.error or {"dps": {str(index): value}}


def test_set_timer_dp_y_segundos():
    c = TimerClient()
    d = TuyaDevice("t", "T", "devid", "1.2.3.4", "key", client=c)
    d.set_timer(2700)
    d.set_timer(0)
    assert c.calls == [("set_value", 9, 2700), ("set_value", 9, 0)]


def test_set_timer_dp_configurable():
    c = TimerClient()
    TuyaDevice("t", "T", "d", "1.2.3.4", "k", timer_dp=11, client=c).set_timer(60)
    assert c.calls == [("set_value", 11, 60)]


def test_set_timer_errores_a_device_error():
    d = make(TimerClient(error={"Error": "Network Error"}))
    with pytest.raises(DeviceError):
        d.set_timer(60)

    class Boom(TimerClient):
        def set_value(self, index, value):
            raise OSError("sin red")

    with pytest.raises(DeviceError):
        make(Boom()).set_timer(60)
