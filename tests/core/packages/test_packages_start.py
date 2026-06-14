"""Units for the install start-phase runner (core/packages/start.py)."""
from core import packages
from core.packages import start


def test_orchestrator_reexports_run_plugin_start_commands() -> None:
    assert packages.run_plugin_start_commands is start.run_plugin_start_commands


def test_run_plugin_start_commands_defers_core_service_restarts() -> None:
    phase, deferred = start.run_plugin_start_commands(
        ["echo hello", "/etc/init.d/S60klipper restart"], {}
    )

    assert phase["id"] == "start"
    assert deferred == ["/etc/init.d/S60klipper restart"]
    # the immediate echo ran inline; only the service restart was deferred
    assert [item["label"] for item in phase["items"]] == ["echo hello"]
