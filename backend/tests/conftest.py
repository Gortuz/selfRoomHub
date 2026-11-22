import pytest
from fastapi.testclient import TestClient

from app.devices.fake import FakeDevice
from app.main import create_app

TOKEN = "test-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client() -> TestClient:
    devices = {
        "lamp": FakeDevice("lamp", "Lámpara"),
        "dead": FakeDevice("dead", "Caído", online=False),
    }
    return TestClient(create_app(devices=devices, token=TOKEN))
