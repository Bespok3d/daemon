"""The deferred-restart batch + verify cycle.

The subprocess and the health probe are the only seams stubbed; the batch assembly (which waits get
appended, the (services) result shape) is exercised for real.
"""
import pytest

from core.results import item
from core.safety import restart_batch


def test_run_restart_batch_waits_for_moonraker_on_a_moonraker_restart(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(restart_batch, "run_one_command", lambda cmd, _env: item(cmd, ok=True))
    monkeypatch.setattr(restart_batch, "moonraker_healthy", lambda: (True, "up"))

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
