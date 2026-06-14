import json
from pathlib import Path

from core import packages
from core.packages import deactivation


def test_orchestrator_reexports_the_deactivation_mechanics() -> None:
    assert packages.neutralize_plugin is deactivation.neutralize_plugin
    assert packages.run_stop_commands is deactivation.run_stop_commands
    assert packages.DEACTIVATED_MARKER is deactivation.DEACTIVATED_MARKER


def test_clear_failure_markers_removes_both_markers(tmp_path: Path) -> None:
    (tmp_path / deactivation.DEACTIVATED_MARKER).write_text("{}")
    (tmp_path / deactivation.RECOVERY_FAILURE_MARKER).write_text("{}")
    deactivation.clear_failure_markers(tmp_path)
    assert not (tmp_path / deactivation.DEACTIVATED_MARKER).exists()
    assert not (tmp_path / deactivation.RECOVERY_FAILURE_MARKER).exists()


def test_deactivate_plugin_without_a_manifest_writes_only_the_marker(tmp_path: Path) -> None:
    deactivation.deactivate_plugin(tmp_path, {}, "broke moonraker")
    marker = json.loads((tmp_path / deactivation.DEACTIVATED_MARKER).read_text())
    assert marker["reason"] == "broke moonraker"


def test_run_stop_commands_runs_each_expanded_command(tmp_path: Path) -> None:
    sentinel = tmp_path / "stopped"
    deactivation.run_stop_commands([f"touch {sentinel}"], {})
    assert sentinel.exists()
