"""The deferred-restart batch + verify cycle.

The jinni's command execution and the health probe are the only seams stubbed; the batch assembly
(which waits get appended, the (services) result shape) is exercised for real. The daemon asks the
jinni to RUN the restart commands (ADR-0037): the stubbed `run_actions` stands in for that actuation
the way a real jinni would answer over the socket.
"""
import pytest

from core.safety import restart_batch
from protocol import ActionResult, DeviceHealth, ServiceHealth
from tests.fakes import FakeKlipperJinni

# The daemon relays service names opaquely; these match the fake klipper jinni's vocabulary.
KLIPPER_SERVICE = "klipper"
MOONRAKER_SERVICE = "moonraker"


def _healthy() -> DeviceHealth:
    return DeviceHealth(
        services={
            KLIPPER_SERVICE: ServiceHealth(ready=True, detail=""),
            MOONRAKER_SERVICE: ServiceHealth(ready=True, detail="up"),
        },
    )


def _ran_ok(commands: list[str]) -> list[ActionResult]:
    return [ActionResult(ok=True, output="") for _ in commands]


def test_run_restart_batch_waits_for_moonraker_on_a_moonraker_restart(
    monkeypatch: pytest.MonkeyPatch, device_jinni: FakeKlipperJinni,
) -> None:
    monkeypatch.setattr(device_jinni, "run_actions", _ran_ok)
    monkeypatch.setattr(device_jinni, "health", _healthy)

    result = restart_batch.run_restart_batch(["/etc/init.d/S61moonraker restart"])

    assert result["plugin_id"] == "(services)"
    assert result["ok"] is True
    labels = [step["label"] for step in result["log"][0]["items"]]
    assert any("moonraker" in label for label in labels)


def test_run_restart_batch_skips_the_health_waits_for_a_non_core_restart(
    monkeypatch: pytest.MonkeyPatch, device_jinni: FakeKlipperJinni,
) -> None:
    monkeypatch.setattr(device_jinni, "run_actions", _ran_ok)

    result = restart_batch.run_restart_batch(["/etc/init.d/S50nginx reload"])

    assert result["ok"] is True
    labels = [step["label"] for step in result["log"][0]["items"]]
    assert not any("come back up" in label for label in labels)
