import pytest

from app import config
from app.devices.fake import FakeDevice


def write(tmp_path, text):
    p = tmp_path / "devices.yaml"
    p.write_text(text)
    return p


def test_interpolacion(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_NAME", "Sala")
    p = write(tmp_path, "devices:\n  - id: a\n    name: ${MY_NAME}\n    type: fake\n")
    devices = config.load_devices(p)
    assert isinstance(devices["a"], FakeDevice)
    assert devices["a"].name == "Sala"


def test_variable_faltante(tmp_path, monkeypatch):
    monkeypatch.delenv("NO_EXISTE", raising=False)
    p = write(tmp_path, "devices:\n  - id: a\n    name: ${NO_EXISTE}\n    type: fake\n")
    with pytest.raises(ValueError, match="NO_EXISTE"):
        config.load_devices(p)


def test_ids_duplicados(tmp_path):
    p = write(
        tmp_path,
        "devices:\n  - {id: a, name: A, type: fake}\n  - {id: a, name: B, type: fake}\n",
    )
    with pytest.raises(ValueError, match="duplicado"):
        config.load_devices(p)


def test_type_desconocido(tmp_path):
    p = write(tmp_path, "devices:\n  - {id: a, name: A, type: zzz}\n")
    with pytest.raises(ValueError, match="zzz"):
        config.load_devices(p)


def test_campos_faltantes(tmp_path):
    p = write(tmp_path, "devices:\n  - {id: a, type: tuya}\n")
    with pytest.raises(ValueError, match="inválida"):
        config.load_devices(p)


def test_token_obligatorio(monkeypatch):
    monkeypatch.delenv("SELFROOMHUB_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="SELFROOMHUB_TOKEN"):
        config.get_token()
