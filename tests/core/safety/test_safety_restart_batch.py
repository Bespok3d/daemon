"""The deferred-restart batch + verify cycle.

The subprocess and the health probe are the only seams stubbed; the batch assembly (which waits get
appended, the (services) result shape) is exercised for real.
"""
import pytest

from core.results import item
from core.safety import restart_batch
from jinni.base import Jinni
from jinni.contracts import KLIPPER_SERVICE, MOONRAKER_SERVICE, DeviceHealth, ServiceHealth


def _healthy() -> DeviceHealth:
    return DeviceHealth(
        services={
            KLIPPER_SERVICE: ServiceHealth(ready=True, detail=""),
            MOONRAKER_SERVICE: ServiceHealth(ready=True, detail="up"),
        },
    )


def test_run_restart_batch_waits_for_moonraker_on_a_moonraker_restart(
    monkeypatch: pytest.MonkeyPatch, device_jinni: Jinni,
) -> None:
    monkeypatch.setattr(restart_batch, "run_one_command", lambda cmd, _env: item(cmd, ok=True))
    monkeypatch.setattr(device_jinni, "health", _healthy)

    result = restart_batch.run_restart_batch(["/etc/init.d/S61moonraker restart"], {})

    assert result["plugin_id"] == "(services)"
    assert result["ok"] is True
    labels = [step["label"] for step in result["log"][0]["items"]]
    assert any("moonraker" in label for label in labels)


def test_run_restart_batch_skips_the_health_waits_for_a_non_core_restart(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(restart_batch, "run_one_command", lambda cmd, _env: item(cmd, ok=True))

    result = restart_batch.run_restart_batch(["/etc/init.d/S50nginx reload"], {})

    assert result["ok"] is True
    labels = [step["label"] for step in result["log"][0]["items"]]
    assert not any("come back up" in label for label in labels)
