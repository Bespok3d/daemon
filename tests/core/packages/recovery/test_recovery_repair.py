# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The narrow setup repair, and a full recover whose caller reboots right after (desktop#30).

A printer that lost only its two include lines got every plugin re-applied, every service restarted,
then a reboot. These tests hold the smaller repair to its promise: it puts the setup right, it
re-applies nothing, and it refuses any fault it does not clear.
"""
import json
from pathlib import Path
from typing import Any

import pytest

from core import packages
from core.packages import repair, setup_repair
from core.packages.recovery import run
from core.packages.recovery.reboot_replaces import REBOOT_REPLACES_RESTART

MP = pytest.MonkeyPatch
KLIPPER_RESTART = "/etc/init.d/S60klipper restart"
VARS = {"BESPOK3D": "/unused"}


def _installed_plugin(plugin_root: Path, plugin_id: str, start: list[str] | None = None) -> None:
    plugin_dir = plugin_root / plugin_id
    plugin_dir.mkdir(parents=True)
    install = {"dirs": [], "symlinks": [], "patches": [], "start": start or []}
    (plugin_dir / "manifest.json").write_text(json.dumps({"name": plugin_id, "version": "0.1.0",
                                                          "install": install}))


def _problem(kind: str, detail: str, plugin_id: str | None = None) -> dict[str, Any]:
    return {"kind": kind, "detail": detail, "plugin_id": plugin_id}


def _report(problems: list[dict[str, Any]], drift: list[dict[str, Any]] | None = None) -> dict:
    return {"switched_off": False, "reboot_required": False, "problems": problems,
            "drift": drift or []}


INCLUDES_GONE = [_problem("includes_missing", "printer.cfg"),
                 _problem("includes_missing", "moonraker.conf")]


def _selfcheck_in_turn(*reports: dict) -> setup_repair.Selfcheck:
    """A selfcheck that answers each call with the next report: before the repair, then after."""
    queue = list(reports)

    def answer(_vars: dict[str, str]) -> dict:
        return queue.pop(0)

    return answer


def _no_reapply(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("the narrow repair re-applied a plugin")


@pytest.fixture
def printer(tmp_path: Path, monkeypatch: MP) -> dict[str, list]:
    """A printer with plugins installed, its roots pointed at tmp, and the jinni calls recorded."""
    plugin_root = tmp_path / "plugins"
    for plugin_id in ("cpu-temp", "spoolman", "print-prefs-core"):
        _installed_plugin(plugin_root, plugin_id, start=[KLIPPER_RESTART])
    monkeypatch.setattr(packages, "PLUGIN_ROOT", plugin_root)
    monkeypatch.setattr(packages, "DATA_ROOT", tmp_path / "data")
    calls: dict[str, list] = {"includes_restored": [], "restarts": []}
    monkeypatch.setattr(repair.jinni_client, "restore_bespok3d_includes",
                        lambda: calls["includes_restored"].append(True))
    return calls


def test_missing_includes_are_put_back_without_reapplying_a_plugin(
    printer: dict[str, list], monkeypatch: MP,
) -> None:
    monkeypatch.setattr(run, "recover_one", _no_reapply)
    monkeypatch.setattr(run, "restart_services", _no_reapply)

    results = packages.repair_setup(VARS, _selfcheck_in_turn(_report(INCLUDES_GONE), _report([])))

    assert printer["includes_restored"] == [True]
    assert [row["plugin_id"] for row in results] == [setup_repair.PRINTER_SETUP_ID]
    assert results[0]["ok"] is True
    assert [entry["label"] for entry in results[0]["log"][0]["items"]] == [
        "printer.cfg", "moonraker.conf"]


def test_the_reported_reinstall_loop_reapplies_none_of_the_installed_plugins(
    printer: dict[str, list], monkeypatch: MP,
) -> None:
    """Bespok3d-desktop#30: two missing includes, and the repair re-applied all 22 plugins. The same
    fault now leaves every installed plugin exactly as it was."""
    reapplied: list[str] = []
    monkeypatch.setattr(run, "recover_one", lambda plugin_dir, *_rest: reapplied.append(plugin_dir.name))  # noqa: E501
    manifests_before = {path: path.read_text()
                        for path in packages.PLUGIN_ROOT.glob("*/manifest.json")}

    packages.repair_setup(VARS, _selfcheck_in_turn(_report(INCLUDES_GONE), _report([])))

    assert reapplied == []
    assert {path: path.read_text()
            for path in packages.PLUGIN_ROOT.glob("*/manifest.json")} == manifests_before


def test_a_problem_still_reported_after_the_repair_fails_its_row(printer: dict[str, list]) -> None:
    still_gone = [_problem("includes_missing", "moonraker.conf")]

    results = packages.repair_setup(VARS, _selfcheck_in_turn(_report(INCLUDES_GONE),
                                                             _report(still_gone)))

    assert results[0]["ok"] is False
    assert [entry["ok"] for entry in results[0]["log"][0]["items"]] == [True, False]


@pytest.mark.parametrize("report", [
    _report([]),
    _report([_problem("plugin_recovery_failed", "spoolman", "spoolman")]),
    _report(INCLUDES_GONE, drift=[{"plugin_id": "spoolman"}]),
    _report([*INCLUDES_GONE, _problem("plugin_recovery_failed", "spoolman", "spoolman")]),
], ids=["nothing wrong", "failed re-apply", "plugin links drifted",
        "includes plus failed re-apply"])
def test_a_fault_the_narrow_repair_does_not_clear_is_refused(
    printer: dict[str, list], report: dict,
) -> None:
    with pytest.raises(packages.NeedsFullRecoverError):
        packages.repair_setup(VARS, _selfcheck_in_turn(report))

    assert printer["includes_restored"] == []


def test_a_recover_with_a_reboot_after_runs_no_services_batch(
    printer: dict[str, list], monkeypatch: MP,
) -> None:
    monkeypatch.setattr(run, "restart_services", _no_reapply)

    results = packages.recover_before_reboot(VARS)

    services = next(row for row in results if row["plugin_id"] == "(services)")
    assert services["ok"] is True
    assert services["reason"] == REBOOT_REPLACES_RESTART
    assert [entry["label"] for entry in services["log"][0]["items"]] == [
        f"left to the reboot: {KLIPPER_RESTART}"]


def test_a_recover_without_a_reboot_after_still_restarts_the_services(
    printer: dict[str, list], monkeypatch: MP,
) -> None:
    def record_restart(_root: Path, held: list[str], *_rest: object) -> dict:
        printer["restarts"].append(held)
        return {"plugin_id": "(services)", "ok": True, "skipped": False, "reason": "", "log": []}

    monkeypatch.setattr(run, "restart_services", record_restart)

    packages.recover(VARS)

    assert printer["restarts"] == [[KLIPPER_RESTART]]
