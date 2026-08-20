# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Switching one plugin off without deleting it (core/packages/deactivator.py).

A plugin other installed plugins need cannot go off quietly: every one of them would keep running
against something that is no longer there. Asked by a person, the daemon refuses and says which
plugins still need it, the same answer uninstall gives; asked with the cascade switch, it takes them
off too, dependents first.
"""

import json
from pathlib import Path

import pytest

from core.packages import deactivator
from core.packages.deactivation import DEACTIVATED_MARKER
from core.packages.errors import DependentsError

FEEDER = "filament-feeder"
FEED_SERVICE = "filament-feed"
SPOOL_TRACKER = "spool-tracker"


def _install(plugin_root: Path, plugin_id: str, manifest: dict) -> None:
    plugin_dir = plugin_root / plugin_id
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text(json.dumps({"name": plugin_id, **manifest}))


def _feeder_with_one_dependent(tmp_path: Path) -> Path:
    plugin_root = tmp_path / "plugins"
    _install(plugin_root, FEEDER, {"provides": [FEED_SERVICE]})
    _install(plugin_root, SPOOL_TRACKER, {"require": [{"service": FEED_SERVICE}]})
    return plugin_root


def _is_off(plugin_root: Path, plugin_id: str) -> bool:
    return (plugin_root / plugin_id / DEACTIVATED_MARKER).exists()


def test_deactivating_a_plugin_another_installed_plugin_needs_is_refused(tmp_path: Path) -> None:
    plugin_root = _feeder_with_one_dependent(tmp_path)

    with pytest.raises(DependentsError) as refusal:
        deactivator.run_deactivate(plugin_root, FEEDER, {})

    assert refusal.value.plugin_id == FEEDER
    assert refusal.value.dependents == [SPOOL_TRACKER]
    assert not _is_off(plugin_root, FEEDER)
    assert not _is_off(plugin_root, SPOOL_TRACKER)


def test_cascade_takes_the_dependents_off_before_the_plugin_they_need(tmp_path: Path) -> None:
    plugin_root = _feeder_with_one_dependent(tmp_path)

    deactivated = deactivator.run_deactivate(plugin_root, FEEDER, {}, cascade=True)

    assert deactivated == [SPOOL_TRACKER, FEEDER]
    assert _is_off(plugin_root, SPOOL_TRACKER)
    assert _is_off(plugin_root, FEEDER)


def test_a_dependent_says_whose_fall_took_it_down(tmp_path: Path) -> None:
    plugin_root = _feeder_with_one_dependent(tmp_path)

    deactivator.run_deactivate(plugin_root, FEEDER, {}, cascade=True)

    marker = json.loads((plugin_root / SPOOL_TRACKER / DEACTIVATED_MARKER).read_text())
    assert FEEDER in marker["reason"]


def test_a_plugin_nothing_needs_goes_off_on_its_own(tmp_path: Path) -> None:
    plugin_root = _feeder_with_one_dependent(tmp_path)

    deactivated = deactivator.run_deactivate(plugin_root, SPOOL_TRACKER, {})

    assert deactivated == [SPOOL_TRACKER]
    assert not _is_off(plugin_root, FEEDER)


def test_a_dependent_already_off_does_not_hold_the_provider_on(tmp_path: Path) -> None:
    # It is already off, so it cannot be stranded, and its own marker says why it went off: that
    # reason is the diagnosis when the safety net put it there, and must not be overwritten.
    plugin_root = _feeder_with_one_dependent(tmp_path)
    (plugin_root / SPOOL_TRACKER / DEACTIVATED_MARKER).write_text(
        json.dumps({"reason": "auto-deactivated: klipper down"})
    )

    deactivated = deactivator.run_deactivate(plugin_root, FEEDER, {})

    assert deactivated == [FEEDER]
    marker = json.loads((plugin_root / SPOOL_TRACKER / DEACTIVATED_MARKER).read_text())
    assert marker["reason"] == "auto-deactivated: klipper down"


def test_deactivating_a_plugin_that_is_not_installed_reports_nothing_deactivated(
        tmp_path: Path) -> None:
    deactivated = deactivator.run_deactivate(tmp_path / "plugins", "ghost", {})

    assert deactivated == []
