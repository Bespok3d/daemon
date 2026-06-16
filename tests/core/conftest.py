"""A device-like jinni for the core tests.

The seam (`core.jinni_client`) asks the loaded jinni for the device's placement classes, restart
commands, service-command classification, and health. The daemon and the jinni are separate apps
that talk over the socket; the daemon never imports the jinni runtime, so the core tests run against
a duck-typed FAKE klipper jinni (tests/fakes.py) that answers those verbs the way a real device
jinni would over the wire. Every consumer reaches it through the one seam, so the autouse fixture
only has to point the seam at the fake.
"""
import pytest

from core import jinni_client
from tests.fakes import FakeKlipperJinni


@pytest.fixture(autouse=True)
def device_jinni(monkeypatch: pytest.MonkeyPatch) -> FakeKlipperJinni:
    jinni = FakeKlipperJinni()
    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", lambda: jinni)
    return jinni
