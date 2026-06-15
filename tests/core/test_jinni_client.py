"""The jinni seam: the daemon's single door to the loaded jinni.

These lock the delegation contract: each verb hands off to the loaded jinni and returns its
serializable result, and the seam never narrows to a printer tier (it asks any jinni, generic or
klipper, the same way). The default transport is in-process; the socket path is covered in
test_jinni_transport.py.
"""
from collections.abc import AsyncIterator

import pytest

from core import jinni_client
from jinni.contracts import (
    KLIPPER_SERVICE,
    MOONRAKER_SERVICE,
    RESTART_KLIPPER,
    DeviceHealth,
    ServiceHealth,
)
from jinni.klipper import KlipperPrinterJinni
from jinni.loader import GenericJinni


class _FakeKlipperJinni(KlipperPrinterJinni):
    id = "fake"

    def device_paths(self) -> dict[str, str]:
        return {key: f"/x/{key}" for key in KlipperPrinterJinni.KLIPPER_PATH_KEYS}

    def restart_command(self, hook: str) -> str | None:
        return {"klipper": "restart-klipper", "moonraker": "restart-moonraker"}.get(hook)

    def capability_flags(self) -> set[str]:
        return {"overlay", "managed-service"}

    def health(self) -> DeviceHealth:
        return DeviceHealth(
            services={
                KLIPPER_SERVICE: ServiceHealth(ready=True, detail="klipper ready"),
                MOONRAKER_SERVICE: ServiceHealth(ready=True, detail="moonraker up"),
            },
        )

    def blocked_actions(self) -> frozenset[str]:
        return frozenset({RESTART_KLIPPER})

    async def watch_blocked_actions(self) -> AsyncIterator[frozenset[str]]:
        yield frozenset({RESTART_KLIPPER})
        yield frozenset()

    def capabilities(self) -> dict:
        return {"adapter": "fake"}


@pytest.fixture
def fake_jinni(monkeypatch: pytest.MonkeyPatch) -> _FakeKlipperJinni:
    jinni = _FakeKlipperJinni()
    monkeypatch.setattr(jinni_client, "get_jinni", lambda: jinni)
    return jinni


def test_paths_delegates(fake_jinni: _FakeKlipperJinni) -> None:
    assert jinni_client.paths() == fake_jinni.paths()


def test_restart_command_delegates(fake_jinni: _FakeKlipperJinni) -> None:
    assert jinni_client.restart_command("klipper") == "restart-klipper"
    assert jinni_client.restart_command("unknown") is None


def test_capability_flags_delegates(fake_jinni: _FakeKlipperJinni) -> None:
    assert jinni_client.capability_flags() == {"overlay", "managed-service"}


def test_health_delegates_to_the_loaded_jinni(fake_jinni: _FakeKlipperJinni) -> None:
    report = jinni_client.health()
    assert report.services[KLIPPER_SERVICE].ready
    assert report.services[MOONRAKER_SERVICE].detail == "moonraker up"
    assert report.healthy is True


def test_blocked_actions_delegates(fake_jinni: _FakeKlipperJinni) -> None:
    assert jinni_client.blocked_actions() == frozenset({RESTART_KLIPPER})


async def test_subscribe_blocked_actions_streams_in_process(fake_jinni: _FakeKlipperJinni) -> None:
    frames = [blocked async for blocked in jinni_client.subscribe_blocked_actions()]
    assert frames == [frozenset({RESTART_KLIPPER}), frozenset()]


def test_capabilities_report_folds_in_interface_extras(fake_jinni: _FakeKlipperJinni) -> None:
    report = jinni_client.capabilities_report()
    assert report["adapter"] == "fake"
    assert "interface_extras" in report


def test_health_on_a_generic_target_reports_no_services(monkeypatch: pytest.MonkeyPatch) -> None:
    # The seam does not narrow to a printer tier: a generic box answers health() too, declaring no
    # critical services (so it is vacuously healthy).
    monkeypatch.setattr(jinni_client, "get_jinni", GenericJinni)
    report = jinni_client.health()
    assert report.services == {}
    assert report.healthy is True
