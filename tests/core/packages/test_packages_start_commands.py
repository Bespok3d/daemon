"""Units for the install start-phase runner (core/packages/start_commands.py)."""
from core.packages import start_commands


def test_run_plugin_start_commands_defers_core_service_restarts() -> None:
    phase, deferred = start_commands.run_plugin_start_commands(
        ["echo hello", "/etc/init.d/S60klipper restart"], {}
    )

    assert phase["id"] == "start"
    assert deferred == ["/etc/init.d/S60klipper restart"]
    # the immediate echo ran inline; only the service restart was deferred
    assert [item["label"] for item in phase["items"]] == ["echo hello"]
