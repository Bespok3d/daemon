# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""White-box units for OTA per-plugin re-apply (core/packages/recovery/reapply.py)."""
import json
from pathlib import Path

import pytest

from core import packages
from core.packages import installer
from core.packages.deactivation import DEACTIVATED_MARKER
from core.packages.recovery import reapply

MP = pytest.MonkeyPatch


def _installed_plugin(plugin_root: Path, plugin_id: str, install: dict | None = None,
                      provides: list | None = None, require: list | None = None) -> dict:
    plugin_dir = plugin_root / plugin_id
    plugin_dir.mkdir(parents=True)
    manifest: dict = {
        "name": plugin_id,
        "version": "0.1.0",
        "install": install or {"dirs": [], "symlinks": [], "patches": [], "start": []},
    }
    if provides is not None:
        manifest["provides"] = provides
    if require is not None:
        manifest["require"] = require
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest))
    return manifest


def test_orchestrator_reexports_recover_one() -> None:
    assert packages.recover_one is reapply.recover_one


def test_recover_one_skips_when_a_dependency_is_unsatisfied(tmp_path: Path) -> None:
    manifest = _installed_plugin(tmp_path, "spoolman", require=[{"service": "rfid"}])

    result, deferred = reapply.recover_one(
        tmp_path / "spoolman", manifest, set(), {"rfid"}, {}
    )

    assert result["skipped"] is True
    assert result["ok"] is False
    assert "rfid" in result["reason"]
    assert deferred == []


def test_recover_one_succeeds_and_clears_a_stale_marker(tmp_path: Path) -> None:
    klipper_restart = "/etc/init.d/S60klipper restart"
    manifest = _installed_plugin(
        tmp_path, "cpu-temp", provides=[{"service": "cpu-temp"}],
        install={"dirs": [], "symlinks": [], "patches": [], "start": [klipper_restart]},
    )
    plugin_dir = tmp_path / "cpu-temp"
    (plugin_dir / reapply.RECOVERY_FAILURE_MARKER).write_text("{}")

    result, deferred = reapply.recover_one(plugin_dir, manifest, set(), set(), {})

    assert result["ok"] is True
    assert deferred == [klipper_restart]
    assert not (plugin_dir / reapply.RECOVERY_FAILURE_MARKER).exists()


def test_recover_one_delegates_to_the_install_spine(tmp_path: Path) -> None:
    # Recovery re-applies through the shared install spine, so it runs the SAME phase sequence a
    # fresh install does, including the modes/dirs/ownership phases the old hand-built list omitted.
    klipper_restart = "/etc/init.d/S60klipper restart"
    manifest = _installed_plugin(
        tmp_path, "cpu-temp",
        install={"dirs": [], "symlinks": [], "patches": [], "start": [klipper_restart]},
    )
    plugin_dir = tmp_path / "cpu-temp"

    result, deferred = reapply.recover_one(plugin_dir, manifest, set(), set(), {})

    assert result["ok"] is True
    assert deferred == [klipper_restart]
    phase_ids = {entry["id"] for entry in result["log"]}
    assert {"modes", "dirs", "ownership"} <= phase_ids


def test_recover_one_isolates_an_unexpected_exception(tmp_path: Path, monkeypatch: MP) -> None:
    # printer-never-broken: a verb that RAISES (not returns ok=False) during one plugin's re-apply
    # must not abort recover. The plugin is deactivated and the real error reported in its result,
    # so the rest still recover and the app shows what failed instead of a bare 500.
    manifest = _installed_plugin(tmp_path, "boom")
    plugin_dir = tmp_path / "boom"

    def explode(*_args: object, **_kwargs: object) -> dict:
        raise RuntimeError("jinni wire blew up")

    monkeypatch.setattr(installer, "create_symlinks", explode)

    result, deferred = reapply.recover_one(plugin_dir, manifest, set(), set(), {})

    assert result["ok"] is False
    assert "recover error" in result["reason"]
    assert "jinni wire blew up" in result["reason"]
    assert deferred == []
    assert (plugin_dir / reapply.RECOVERY_FAILURE_MARKER).exists()


def test_recover_one_unwires_a_failed_plugin(tmp_path: Path, monkeypatch: MP) -> None:
    # printer-never-broken, the tail of the OTA arc: a re-apply that gets as far as wiring the
    # plugin's config into place and THEN fails must leave nothing of that plugin in effect, while
    # the plugin's own files stay on disk for a fixed version to revive.
    wired_config = tmp_path / "etc" / "cpu-temp.cfg"
    manifest = _installed_plugin(
        tmp_path, "cpu-temp",
        install={"dirs": [], "patches": [], "start": [],
                 "symlinks": [{"from": "files/cpu-temp.cfg", "to": str(wired_config)}]},
    )
    plugin_dir = tmp_path / "cpu-temp"
    (plugin_dir / "files").mkdir()
    (plugin_dir / "files" / "cpu-temp.cfg").write_text("[cpu_temp]\n")
    monkeypatch.setattr(installer, "apply_patches",
                        lambda *_a, **_kw: {"id": "patches", "ok": False, "items": []})

    result, deferred = reapply.recover_one(plugin_dir, manifest, set(), set(), {})

    assert result["ok"] is False
    assert "install phase failed" in result["reason"]  # it got past the wire, so the wire happened
    assert deferred == []
    assert not wired_config.exists()
    assert (plugin_dir / "files" / "cpu-temp.cfg").exists()
    assert (plugin_dir / DEACTIVATED_MARKER).exists()


def test_recover_one_deactivates_when_a_phase_fails(tmp_path: Path, monkeypatch: MP) -> None:
    manifest = _installed_plugin(tmp_path, "broken")
    plugin_dir = tmp_path / "broken"
    monkeypatch.setattr(installer, "render_templates",
                        lambda *_a, **_kw: {"id": "templates", "ok": False, "items": []})

    result, deferred = reapply.recover_one(plugin_dir, manifest, set(), set(), {})

    assert result["ok"] is False
    assert "install phase failed" in result["reason"]
    assert deferred == []
    assert (plugin_dir / reapply.RECOVERY_FAILURE_MARKER).exists()
