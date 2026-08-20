# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Uncovered refuse/survive edges for OTA recovery (reapply.py + run.py).

Every case here is a printer state the happy-path suite never puts recovery through: a required
setting recovery cannot supply, a provider that fails mid-sweep, a mutual dependency cycle, and an
install set with nothing left to recover. The governing invariant is the same in all four: a plugin
recovery cannot restore is switched off loudly with its files kept, and one plugin's trouble never
stops the rest of the sweep.
"""
import json
from pathlib import Path

import pytest

from core.packages import installer
from core.packages.deactivation import DEACTIVATED_MARKER
from core.packages.recovery import reapply, run
from core.packages.recovery.reapply import ServiceLedger

MP = pytest.MonkeyPatch
BARE_INSTALL: dict[str, list[str]] = {"dirs": [], "symlinks": [], "patches": [], "start": []}


def _plugin(plugin_root: Path, plugin_id: str, manifest: dict) -> dict:
    plugin_dir = plugin_root / plugin_id
    plugin_dir.mkdir(parents=True)
    full_manifest = {"name": plugin_id, **manifest}
    (plugin_dir / "manifest.json").write_text(json.dumps(full_manifest))
    return full_manifest


def test_missing_required_variable_switches_the_plugin_off(tmp_path: Path) -> None:
    """A required setting recovery cannot supply must fail loud, not stay wired half-applied."""
    manifest = _plugin(tmp_path, "spoolman", {
        "version": "0.1.0", "install": BARE_INSTALL,
        "requires": {"variables": [{"name": "SPOOLMAN_SERVER", "required": True}]},
    })
    plugin_dir = tmp_path / "spoolman"

    result, deferred = reapply.recover_one(plugin_dir, manifest, ServiceLedger(set(), set()), {})

    assert result["ok"] is False
    assert "SPOOLMAN_SERVER" in result["reason"]
    assert deferred == []
    assert (plugin_dir / DEACTIVATED_MARKER).exists()


def test_run_recovery_skips_a_dependent_when_its_provider_fails(
        tmp_path: Path, monkeypatch: MP) -> None:
    """A provider that fails its own re-apply must not let the sweep recover its dependent too."""
    plugin_root = tmp_path / "plugins"
    _plugin(plugin_root, "sensor-hub", {
        "version": "0.1.0", "install": BARE_INSTALL, "provides": [{"service": "rfid"}],
    })
    _plugin(plugin_root, "spoolman", {
        "version": "0.1.0", "install": BARE_INSTALL, "require": [{"service": "rfid"}],
    })
    monkeypatch.setattr(installer, "render_templates",
                        lambda *_a, **_kw: {"id": "templates", "ok": False, "items": []})

    results = run.run_recovery(tmp_path / "data", plugin_root, {})

    by_id = {result["plugin_id"]: result for result in results}
    assert by_id["sensor-hub"]["ok"] is False
    assert (plugin_root / "sensor-hub" / DEACTIVATED_MARKER).exists()
    assert by_id["spoolman"] == {
        "plugin_id": "spoolman", "ok": False, "skipped": True,
        "reason": "dependency not satisfied: rfid", "log": [],
    }


def test_run_recovery_survives_a_mutual_dependency_cycle(tmp_path: Path) -> None:
    """Two plugins requiring each other's service must not hang or crash the whole sweep."""
    plugin_root = tmp_path / "plugins"
    _plugin(plugin_root, "first", {
        "version": "0.1.0", "install": BARE_INSTALL,
        "provides": [{"service": "first-feed"}], "require": [{"service": "second-feed"}],
    })
    _plugin(plugin_root, "second", {
        "version": "0.1.0", "install": BARE_INSTALL,
        "provides": [{"service": "second-feed"}], "require": [{"service": "first-feed"}],
    })

    results = run.run_recovery(tmp_path / "data", plugin_root, {})

    assert {result["plugin_id"] for result in results} == {"first", "second"}
    assert all(result["skipped"] and not result["ok"] for result in results)
    assert not (plugin_root / "first" / DEACTIVATED_MARKER).exists()
    assert not (plugin_root / "second" / DEACTIVATED_MARKER).exists()


def test_run_recovery_returns_nothing_when_every_plugin_is_deactivated(tmp_path: Path) -> None:
    """An install set with nothing left to recover must come back empty, never crash."""
    plugin_root = tmp_path / "plugins"
    _plugin(plugin_root, "idle-timeout", {"version": "0.1.0", "install": BARE_INSTALL})
    (plugin_root / "idle-timeout" / DEACTIVATED_MARKER).write_text("{}")

    results = run.run_recovery(tmp_path / "data", plugin_root, {})

    assert results == []
