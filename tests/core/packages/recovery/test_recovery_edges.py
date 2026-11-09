# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Uncovered refuse/survive edges for OTA recovery (reapply.py + run.py).

Every case here is a printer state the happy-path suite never puts recovery through: a required
setting recovery cannot supply, a provider that fails mid-sweep, a mutual dependency cycle, and an
install set with nothing left to recover. The governing invariant is the same in every one: a plugin
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
from core.packages.templates import render_templates

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


def _render_failing_for_power_a(templates: list[dict], plugin_dir: Path,
                                vars: dict[str, str]) -> dict:
    if plugin_dir.name == "power-a":
        return {"id": "templates", "ok": False, "items": []}
    return render_templates(templates, plugin_dir, vars)


def test_a_dependent_waits_for_a_second_provider_coming_back_later_in_the_same_recovery(
        tmp_path: Path, monkeypatch: MP) -> None:
    """Two plugins give power and two give rfid, and one rfid giver needs power while one power
    giver needs rfid, so no order fixed beforehand fits every failure. The first power giver fails:
    the rfid giver that needs power must wait for the other power giver, never be switched off
    while it is still on its way."""
    plugin_root = tmp_path / "plugins"
    recovery_order = ["rfid-base", "power-a", "rfid-reader", "power-tags"]
    _plugin(plugin_root, "rfid-base", {
        "version": "0.1.0", "install": BARE_INSTALL, "provides": [{"service": "rfid"}],
    })
    _plugin(plugin_root, "power-a", {
        "version": "0.1.0", "install": BARE_INSTALL, "provides": [{"service": "power"}],
    })
    _plugin(plugin_root, "rfid-reader", {
        "version": "0.1.0", "install": BARE_INSTALL,
        "provides": [{"service": "rfid"}], "require": [{"service": "power"}],
    })
    _plugin(plugin_root, "power-tags", {
        "version": "0.1.0", "install": BARE_INSTALL,
        "provides": [{"service": "power"}], "require": [{"service": "rfid"}],
    })
    monkeypatch.setattr(run, "recoverable_plugin_dirs",
                        lambda root: [root / plugin_id for plugin_id in recovery_order])
    monkeypatch.setattr(installer, "render_templates", _render_failing_for_power_a)

    results = run.run_recovery(tmp_path / "data", plugin_root, {})

    by_id = {result["plugin_id"]: result for result in results}
    assert by_id["power-a"]["ok"] is False
    assert by_id["power-tags"]["ok"] is True
    assert by_id["rfid-reader"]["ok"] is True
    assert not (plugin_root / "rfid-reader" / DEACTIVATED_MARKER).exists()


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
    assert (plugin_root / "first" / DEACTIVATED_MARKER).exists()
    assert (plugin_root / "second" / DEACTIVATED_MARKER).exists()


def test_run_recovery_switches_off_a_dependent_its_failed_provider_left_wired(
        tmp_path: Path, monkeypatch: MP) -> None:
    """After a firmware update the dependent's extras are gone but its config link is still in
    Klipper's config. Skipped and left wired, it stops Klipper at every boot; it must come off the
    printer like a failed plugin, its files kept and its marker naming the missing dependency."""
    plugin_root = tmp_path / "plugins"
    _plugin(plugin_root, "rfid-reader", {
        "version": "0.1.0", "install": BARE_INSTALL, "provides": [{"service": "rfid"}],
    })
    klipper_config_link = tmp_path / "config" / "afc-lite.cfg"
    _plugin(plugin_root, "afc-lite", {
        "version": "0.1.0", "require": [{"service": "rfid"}],
        "install": {**BARE_INSTALL,
                    "symlinks": [{"from": "files/afc-lite.cfg", "to": str(klipper_config_link)}]},
    })
    plugin_config = plugin_root / "afc-lite" / "files" / "afc-lite.cfg"
    plugin_config.parent.mkdir()
    plugin_config.write_text("[afc]\n")
    klipper_config_link.parent.mkdir()
    klipper_config_link.symlink_to(plugin_config)
    monkeypatch.setattr(installer, "render_templates",
                        lambda *_a, **_kw: {"id": "templates", "ok": False, "items": []})

    results = run.run_recovery(tmp_path / "data", plugin_root, {})

    by_id = {result["plugin_id"]: result for result in results}
    assert by_id["afc-lite"] == {
        "plugin_id": "afc-lite", "ok": False, "skipped": True,
        "reason": "dependency not satisfied: rfid", "log": [],
    }
    assert not klipper_config_link.is_symlink()
    assert plugin_config.exists()
    marker = json.loads((plugin_root / "afc-lite" / DEACTIVATED_MARKER).read_text())
    assert marker == {"reason": "dependency not satisfied: rfid"}


def test_run_recovery_returns_nothing_when_every_plugin_is_deactivated(tmp_path: Path) -> None:
    """An install set with nothing left to recover must come back empty, never crash."""
    plugin_root = tmp_path / "plugins"
    _plugin(plugin_root, "idle-timeout", {"version": "0.1.0", "install": BARE_INSTALL})
    (plugin_root / "idle-timeout" / DEACTIVATED_MARKER).write_text("{}")

    results = run.run_recovery(tmp_path / "data", plugin_root, {})

    assert results == []


def test_one_torn_manifest_is_switched_off_while_every_other_plugin_recovers(
        tmp_path: Path) -> None:
    """A manifest half written when the power went is there but unreadable. That one plugin is
    switched off and named in what recovery reports back; the rest of the printer still comes back,
    instead of the whole sweep dying on the unreadable file."""
    plugin_root = tmp_path / "plugins"
    _plugin(plugin_root, "good-plugin", {"version": "0.1.0", "install": BARE_INSTALL})
    torn_dir = plugin_root / "torn-plugin"
    torn_dir.mkdir(parents=True)
    (torn_dir / "manifest.json").write_text("{ this manifest was torn by a power cut")

    results = run.run_recovery(tmp_path / "data", plugin_root, {})

    by_id = {result["plugin_id"]: result for result in results}
    assert by_id["good-plugin"]["ok"] is True
    assert by_id["torn-plugin"]["ok"] is False
    assert "manifest" in by_id["torn-plugin"]["reason"]
    assert (torn_dir / DEACTIVATED_MARKER).exists()
