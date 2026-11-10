# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A recover whose caller reboots right after still gets the safety net, once the printer is back.

The reboot replaces the services restart, so the net cannot look at the printer at the end of the
recover. Before this check, a plugin that broke the printer after such a recover stayed on it: the
app showed a clean report and nothing was taken off.
"""
import json
import logging
from pathlib import Path

import pytest

from core.packages.errors import BlockedActionError
from core.packages.recovery import reboot_replaces, restart
from core.results import SERVICES_PLUGIN_ID
from core.safety import AttributionIndex, FailureEvidence, OperationContext
from core.safety.decision import Decision
from protocol import DeviceHealth, FailureSignals, ServiceHealth

KLIPPER_RESTART = "/etc/init.d/S60klipper restart"
PLUGIN_SERVICE_RESTART = "/etc/init.d/S65camera-hw restart"
PLUGIN = "spoolman"
CORE_SERVICE = "klipper"


def _evidence(ready: bool) -> FailureEvidence:
    return FailureEvidence(
        health=DeviceHealth(services={CORE_SERVICE: ServiceHealth(ready=ready, detail="")},
                            diagnosis="", signals=FailureSignals()),
        index=AttributionIndex(by_path={}, by_module={}, by_section={}),
    )


def _plugin_root(tmp_path: Path) -> Path:
    plugin_dir = tmp_path / "plugins" / PLUGIN
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text(json.dumps({"name": PLUGIN}))
    return tmp_path / "plugins"


def _printer_after_reboot(monkeypatch: pytest.MonkeyPatch, readiness: list[bool]) -> dict:
    """Each evidence gathering answers with the next readiness; the net blames the plugin and its
    deactivations and restarts are recorded instead of run."""
    seen: dict[str, list] = {"peeled": [], "restarts": []}

    def next_evidence(_root: Path, _vars: dict[str, str]) -> FailureEvidence:
        return _evidence(readiness.pop(0))

    def blame_the_plugin(_evidence: FailureEvidence, _ctx: OperationContext,
                         already: list[str] | None = None) -> Decision:
        culprit = None if PLUGIN in (already or []) else PLUGIN
        return Decision(culprit=culprit, signal="klipper down", fixer="stub")

    def record_peel(_root: Path, plugin_id: str, _vars: dict[str, str], _why: str) -> list[str]:
        seen["peeled"].append(plugin_id)
        return [plugin_id]

    monkeypatch.setattr(reboot_replaces, "guard_no_print", lambda: None)
    monkeypatch.setattr(reboot_replaces, "touches_core_service",
                        lambda held: KLIPPER_RESTART in held)
    monkeypatch.setattr(restart, "gather_evidence", next_evidence)
    monkeypatch.setattr(restart, "decide", blame_the_plugin)
    monkeypatch.setattr(restart, "deactivate_with_dependents", record_peel)
    monkeypatch.setattr(restart, "run_restart_batch", seen["restarts"].append)
    return seen


def test_a_plugin_that_breaks_the_printer_after_the_reboot_is_taken_off(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _printer_after_reboot(monkeypatch, [False, True])
    data_root = tmp_path / "data"
    reboot_replaces.leave_restarts_to_reboot(data_root, [KLIPPER_RESTART])

    rows = reboot_replaces.check_after_reboot(data_root, _plugin_root(tmp_path), {})

    assert seen["peeled"] == [PLUGIN]
    assert seen["restarts"] == [[KLIPPER_RESTART]]
    assert [(row["plugin_id"], row["ok"], row["auto_deactivated"]) for row in rows] == [
        (PLUGIN, False, PLUGIN), (SERVICES_PLUGIN_ID, True, PLUGIN)]
    assert not (data_root / reboot_replaces.RESTARTS_LEFT_TO_REBOOT).exists()


def test_a_printer_back_healthy_gets_a_healthy_row_and_nothing_taken_off(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _printer_after_reboot(monkeypatch, [True])
    data_root = tmp_path / "data"
    reboot_replaces.leave_restarts_to_reboot(data_root, [KLIPPER_RESTART])

    rows = reboot_replaces.check_after_reboot(data_root, _plugin_root(tmp_path), {})

    assert seen["peeled"] == []
    assert [(row["ok"], row["reason"]) for row in rows] == [
        (True, reboot_replaces.HEALTHY_AFTER_REBOOT)]
    assert not (data_root / reboot_replaces.RESTARTS_LEFT_TO_REBOOT).exists()


def test_no_restart_left_to_the_reboot_means_no_check(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    readiness: list[bool] = []
    _printer_after_reboot(monkeypatch, readiness)

    rows = reboot_replaces.check_after_reboot(tmp_path / "data", _plugin_root(tmp_path), {})

    assert rows == []


def test_the_net_logs_whom_it_blamed(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    _printer_after_reboot(monkeypatch, [False, True])
    data_root = tmp_path / "data"
    reboot_replaces.leave_restarts_to_reboot(data_root, [KLIPPER_RESTART])

    with caplog.at_level(logging.INFO, logger=restart.__name__):
        reboot_replaces.check_after_reboot(data_root, _plugin_root(tmp_path), {})

    assert f"stub blamed {PLUGIN} (klipper down)" in caplog.text


def test_a_check_that_fails_keeps_the_restarts_for_the_next_call(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _printer_after_reboot(monkeypatch, [])
    data_root = tmp_path / "data"
    reboot_replaces.leave_restarts_to_reboot(data_root, [KLIPPER_RESTART])

    with pytest.raises(IndexError):
        reboot_replaces.check_after_reboot(data_root, _plugin_root(tmp_path), {})

    assert (data_root / reboot_replaces.RESTARTS_LEFT_TO_REBOOT).exists()


def test_restarts_that_touch_no_core_service_get_no_check(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _printer_after_reboot(monkeypatch, [])
    data_root = tmp_path / "data"
    reboot_replaces.leave_restarts_to_reboot(data_root, [PLUGIN_SERVICE_RESTART])

    rows = reboot_replaces.check_after_reboot(data_root, _plugin_root(tmp_path), {})

    assert (rows, seen["peeled"]) == ([], [])
    assert not (data_root / reboot_replaces.RESTARTS_LEFT_TO_REBOOT).exists()


def test_a_check_refused_mid_print_keeps_the_restarts_for_the_next_call(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse_mid_print() -> None:
        raise BlockedActionError(frozenset({"restart-klipper"}))

    seen = _printer_after_reboot(monkeypatch, [])
    monkeypatch.setattr(reboot_replaces, "guard_no_print", refuse_mid_print)
    data_root = tmp_path / "data"
    reboot_replaces.leave_restarts_to_reboot(data_root, [KLIPPER_RESTART])

    with pytest.raises(BlockedActionError):
        reboot_replaces.check_after_reboot(data_root, _plugin_root(tmp_path), {})

    assert seen["peeled"] == []
    assert (data_root / reboot_replaces.RESTARTS_LEFT_TO_REBOOT).exists()
