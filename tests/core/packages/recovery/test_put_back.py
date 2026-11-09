# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Recovery puts back a plugin the safety net switched off, and the plugins taken off with it.

The bench case: a firmware update wiped the files a plugin links into the printer, the safety net
saw its component fail to load and switched it off before recovery ran, and recovery left it off, so
a working plugin was silently lost. A plugin a person switched off stays off.

The plugins are made up and wire nothing, so the re-apply always succeeds."""
import json
from pathlib import Path

import pytest

from core.packages.deactivation import DEACTIVATED_MARKER
from core.packages.deactivator import REQUESTED_REASON, run_deactivate
from core.packages.recovery import restart
from core.packages.recovery.put_back import plugins_to_put_back
from core.packages.recovery.run import run_recovery
from core.packages.switched_off_marker import (
    AUTO_DEACTIVATED_PREFIX,
    stranded_on_request_reason,
    stranded_reason,
)
from core.safety import FailureEvidence, OperationContext, OperationKind
from core.safety.decision import Decision
from tests.core.packages.recovery.printer_down import printer_down

BARE_INSTALL: dict[str, list[str]] = {"dirs": [], "symlinks": [], "patches": [], "start": []}
WIPED_COMPONENT = f"{AUTO_DEACTIVATED_PREFIX}component 'fake_proxy' failed to load"
FILAMENT_TRACKER = "filament-tracker"
TRACKER_PANEL = "tracker-panel"
PLUGINS = "plugins"
TRACKING = "tracking"
PROVIDES_TRACKING = {"provides": [{"service": TRACKING}]}
NEEDS_TRACKING = {"require": [{"service": TRACKING}]}


def _installed_plugin(plugin_root: Path, plugin_id: str,
                      services: dict[str, list[dict[str, str]]]) -> Path:
    plugin_dir = plugin_root / plugin_id
    plugin_dir.mkdir(parents=True)
    manifest = {"name": plugin_id, "version": "0.1.0", "install": BARE_INSTALL, **services}
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest))
    return plugin_dir


def _switched_off_plugin(plugin_root: Path, plugin_id: str, reason: str,
                         services: dict[str, list[dict[str, str]]]) -> Path:
    plugin_dir = _installed_plugin(plugin_root, plugin_id, services)
    (plugin_dir / DEACTIVATED_MARKER).write_text(json.dumps({"reason": reason}))
    return plugin_dir


def _tracker_and_its_panel(plugin_root: Path, tracker_reason: str,
                          panel_reason: str) -> tuple[Path, Path]:
    """A plugin giving the tracking service, switched off for `tracker_reason`, and a plugin that
    needs it, switched off with it for `panel_reason`."""
    tracker = _switched_off_plugin(plugin_root, FILAMENT_TRACKER, tracker_reason,
                                   PROVIDES_TRACKING)
    panel = _switched_off_plugin(plugin_root, TRACKER_PANEL, panel_reason, NEEDS_TRACKING)
    return tracker, panel


def test_a_plugin_the_safety_net_switched_off_comes_back_on(tmp_path: Path) -> None:
    tracker = _switched_off_plugin(tmp_path / PLUGINS, FILAMENT_TRACKER, WIPED_COMPONENT, {})

    results = run_recovery(tmp_path / "data", tmp_path / PLUGINS, {})

    assert [(row["plugin_id"], row["ok"]) for row in results] == [(FILAMENT_TRACKER, True)]
    assert not (tracker / DEACTIVATED_MARKER).exists()


def test_a_plugin_switched_off_with_the_one_it_needs_comes_back_with_it(tmp_path: Path) -> None:
    tracker, panel = _tracker_and_its_panel(tmp_path / PLUGINS, WIPED_COMPONENT,
                                           stranded_reason(FILAMENT_TRACKER))

    results = run_recovery(tmp_path / "data", tmp_path / PLUGINS, {})

    assert [(row["plugin_id"], row["ok"]) for row in results] == [
        (FILAMENT_TRACKER, True), (TRACKER_PANEL, True)]
    assert not (tracker / DEACTIVATED_MARKER).exists()
    assert not (panel / DEACTIVATED_MARKER).exists()


def test_a_plugin_a_person_switched_off_stays_off_with_the_ones_it_took_along(
    tmp_path: Path,
) -> None:
    tracker, panel = _tracker_and_its_panel(
        tmp_path / PLUGINS, REQUESTED_REASON, stranded_on_request_reason(FILAMENT_TRACKER))

    results = run_recovery(tmp_path / "data", tmp_path / PLUGINS, {})

    assert results == []
    assert (tracker / DEACTIVATED_MARKER).exists()
    assert (panel / DEACTIVATED_MARKER).exists()


def test_a_plugin_a_person_switched_off_stays_off_after_its_provider_comes_back(
    tmp_path: Path,
) -> None:
    """A person switched the tracker off and the panel with it. The tracker's marker is then made
    the safety net's, as when the tracker was switched back on and the net took it off again:
    recovery puts the tracker back, not the panel."""
    plugin_root = tmp_path / PLUGINS
    tracker = _installed_plugin(plugin_root, FILAMENT_TRACKER, PROVIDES_TRACKING)
    panel = _installed_plugin(plugin_root, TRACKER_PANEL, NEEDS_TRACKING)
    run_deactivate(plugin_root, FILAMENT_TRACKER, {}, cascade=True)
    (tracker / DEACTIVATED_MARKER).write_text(json.dumps({"reason": WIPED_COMPONENT}))

    results = run_recovery(tmp_path / "data", plugin_root, {})

    assert [(row["plugin_id"], row["ok"]) for row in results] == [(FILAMENT_TRACKER, True)]
    assert not (tracker / DEACTIVATED_MARKER).exists()
    assert (panel / DEACTIVATED_MARKER).exists()


@pytest.mark.parametrize(("operation", "put_back"), [
    (OperationKind.INSTALL, [FILAMENT_TRACKER, TRACKER_PANEL]),
    (OperationKind.RECOVER, []),
])
def test_a_plugin_that_fails_again_during_a_recovery_stays_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: OperationKind,
    put_back: list[str],
) -> None:
    """A recovery links every plugin again, so one that still breaks the printer then really fails:
    the next recovery leaves it and the plugins taken off with it off, instead of putting them back
    each time."""
    plugin_root = tmp_path / PLUGINS
    tracker = _installed_plugin(plugin_root, FILAMENT_TRACKER, PROVIDES_TRACKING)
    panel = _installed_plugin(plugin_root, TRACKER_PANEL, NEEDS_TRACKING)
    _net_blames_the_tracker(monkeypatch)

    ctx = restart.op_context(operation, {"name": FILAMENT_TRACKER})
    restart._auto_recover(plugin_root, ["restart klipper"], {}, ctx, printer_down())

    assert (tracker / DEACTIVATED_MARKER).exists()
    assert (panel / DEACTIVATED_MARKER).exists()
    assert [plugin_dir.name for plugin_dir in plugins_to_put_back(plugin_root)] == put_back


def _net_blames_the_tracker(monkeypatch: pytest.MonkeyPatch) -> None:
    def blame_the_tracker(evidence: FailureEvidence, ctx: OperationContext,
                          already: list[str] | None = None) -> Decision:
        culprit = None if FILAMENT_TRACKER in (already or []) else FILAMENT_TRACKER
        return Decision(culprit=culprit, signal="klipper down", fixer="stub")

    def still_down(root: Path, plugin_vars: dict[str, str]) -> FailureEvidence:
        return printer_down()

    monkeypatch.setattr(restart, "decide", blame_the_tracker)
    monkeypatch.setattr(restart, "gather_evidence", still_down)
    monkeypatch.setattr(restart, "run_restart_batch", lambda commands: None)
