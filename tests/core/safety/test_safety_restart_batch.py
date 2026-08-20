# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
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


def _reporting_nothing() -> DeviceHealth:
    """A printer that ran the restart and then told us nothing about that service."""
    return DeviceHealth(services={})


def test_a_service_the_printer_never_reports_on_counts_as_not_back_up(
    monkeypatch: pytest.MonkeyPatch, device_jinni: FakeKlipperJinni,
) -> None:
    """The restart and the health report are two separate answers and they can disagree. When the
    second one leaves out a service the first one restarted, the batch must fail so the safety net
    takes the plugin out of the way; a crash here would leave the printer with no safety net."""
    monkeypatch.setattr(device_jinni, "run_actions", _ran_ok)
    monkeypatch.setattr(device_jinni, "health", _reporting_nothing)
    monkeypatch.setattr(device_jinni, "prune_dead_config_links", lambda: [])

    result = restart_batch.run_restart_batch(["/etc/init.d/S61moonraker restart"])

    assert result["ok"] is False
    assert result["reason"] == "a restarted service did not come back up"


def test_the_unreported_service_is_named_in_the_log_the_user_sees(
    monkeypatch: pytest.MonkeyPatch, device_jinni: FakeKlipperJinni,
) -> None:
    monkeypatch.setattr(device_jinni, "run_actions", _ran_ok)
    monkeypatch.setattr(device_jinni, "health", _reporting_nothing)
    monkeypatch.setattr(device_jinni, "prune_dead_config_links", lambda: [])

    result = restart_batch.run_restart_batch(["/etc/init.d/S61moonraker restart"])

    waits = [step for step in result["log"][0]["items"]
             if step["label"] == f"wait for {MOONRAKER_SERVICE} to come back up"]
    assert waits and waits[0]["ok"] is False
    assert waits[0]["output"] == "the printer did not report on this service"
