# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""White-box units for OTA per-plugin re-apply (core/packages/recovery/reapply.py)."""
import json
from pathlib import Path

import pytest

from core import packages
from core.packages import installer, repair
from core.packages.deactivation import DEACTIVATED_MARKER
from core.packages.recovery import reapply
from tests.package_fixtures import files_entries

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


def test_recover_one_re_applies_a_rendered_over_file_every_time(tmp_path: Path) -> None:
    # mainsail and fluidd both ship the file their own template renders over, so the packer's
    # sha256 covers the pre-render copy. The first re-apply overwrites it; a second one would hash
    # the rendered text against that pre-render sha256 and deactivate the plugin for tampering.
    button_source = "files/b3d-tool-buttons.js.tmpl"
    button_target = "files/html/b3d-tool-buttons.js"
    manifest = _installed_plugin(
        tmp_path, "mainsail",
        install={"dirs": [], "symlinks": [], "patches": [], "start": [],
                 "templates": [{"from": button_source, "to": button_target}]},
    )
    plugin_dir = tmp_path / "mainsail"
    (plugin_dir / "files" / "html").mkdir(parents=True)
    (plugin_dir / button_source).write_text("const moonraker = '$MOONRAKER_URL'\n")
    (plugin_dir / button_target).write_text("const moonraker = '$MOONRAKER_URL'\n")
    manifest["files"] = files_entries({
        button_source: (plugin_dir / button_source).read_text(),
        button_target: (plugin_dir / button_target).read_text(),
    })
    vars = {"MOONRAKER_URL": "http://127.0.0.1:7125"}

    first, _ = reapply.recover_one(plugin_dir, manifest, set(), set(), vars)
    second, _ = reapply.recover_one(plugin_dir, manifest, set(), set(), vars)

    assert first["ok"] is True
    assert second["ok"] is True, second["reason"]
    assert (plugin_dir / button_target).read_text() == "const moonraker = 'http://127.0.0.1:7125'\n"
    assert not (plugin_dir / DEACTIVATED_MARKER).exists()


def test_recover_wires_the_printer_config_back_up(tmp_path: Path, monkeypatch: MP) -> None:
    """Recovery on a live printer must leave klipper actually loading the plugins it re-applied.

    Deactivation strips the `[include bespok3d/...]` lines from the printer's own config, and only
    the jinni can put them back, so recovery that skipped the call left every plugin installed,
    linked and ignored.
    """
    rewired: list[bool] = []
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path / "plugins")
    monkeypatch.setattr(packages, "DATA_ROOT", tmp_path / "data")
    monkeypatch.setattr(repair.jinni_client, "restore_bespok3d_includes",
                        lambda: rewired.append(True))

    packages.recover({"BESPOK3D": str(tmp_path)})

    assert rewired == [True]


def test_recover_leaves_a_deactivated_printer_unwired(tmp_path: Path, monkeypatch: MP) -> None:
    data_root = tmp_path / "data"
    (data_root / "etc").mkdir(parents=True)
    (data_root / packages.GLOBAL_DEACTIVATED_MARKER).write_text("")
    rewired: list[bool] = []
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path / "plugins")
    monkeypatch.setattr(packages, "DATA_ROOT", data_root)
    monkeypatch.setattr(repair.jinni_client, "restore_bespok3d_includes",
                        lambda: rewired.append(True))

    packages.recover({"BESPOK3D": str(tmp_path)})

    assert rewired == []
