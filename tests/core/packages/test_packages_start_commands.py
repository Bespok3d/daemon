"""Units for the install start-phase runner (core/packages/start_commands.py)."""
import pytest

from core.packages import start_commands
from protocol import ActionResult
from tests.fakes import FakeKlipperJinni


def test_run_plugin_start_commands_defers_core_service_restarts(
    device_jinni: FakeKlipperJinni,
) -> None:
    phase, deferred = start_commands.run_plugin_start_commands(
        ["echo hello", "/etc/init.d/S60klipper restart"], {}
    )

    assert phase["id"] == "start"
    assert deferred == ["/etc/init.d/S60klipper restart"]
    # the immediate echo ran; only the service restart was deferred
    assert [item["label"] for item in phase["items"]] == ["echo hello"]


def test_run_plugin_start_commands_runs_the_immediates_through_the_jinni(
    monkeypatch: pytest.MonkeyPatch, device_jinni: FakeKlipperJinni,
) -> None:
    """The daemon does not execute a device command itself (ADR-0037): the immediate commands go to
    the jinni's run_actions, and its results become the phase items."""
    ran: list[list[str]] = []

    def spy(commands: list[str]) -> list[ActionResult]:
        ran.append(commands)
        return [ActionResult(ok=True, output="done") for _ in commands]

    monkeypatch.setattr(device_jinni, "run_actions", spy)

    phase, _deferred = start_commands.run_plugin_start_commands(["echo one", "echo two"], {})

    assert ran == [["echo one", "echo two"]]
    assert [item["output"] for item in phase["items"]] == ["done", "done"]
