# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a package refused AFTER it was unpacked leaves on the printer.

Some refusals can only be decided once the package is on disk, and taking that extraction back off
is what keeps the daemon from reporting a plugin it never applied. A new version is unpacked into
the directory the working version already lives in, and that directory holds the only copies of the
stock files the working version patched. Taking those away with the rest costs the printer its way
back to stock for good, so they are the one thing a refusal keeps.

The fixture printer is fake throughout: made-up plugin ids and made-up device paths under tmp_path.
"""

from pathlib import Path

from core.packages import batch_one
from tests.package_fixtures import package_bytes

NEEDS_A_SETTING = {"requires": {"variables": [{"name": "SPOOLMAN_SERVER", "required": True}]}}


def _package_the_printer_will_refuse(tmp_path: Path, plugin_id: str) -> Path:
    """A package declaring a setting it cannot be applied without, so the refusal lands after the
    package is already unpacked."""
    manifest = {
        "name": plugin_id,
        "version": "0.2.0",
        "install": {"dirs": [], "symlinks": [], "patches": [], "start": [], "templates": []},
        **NEEDS_A_SETTING,
    }
    package_path = tmp_path / f"{plugin_id}.b3"
    package_path.write_bytes(package_bytes(manifest, {"files/settings.cfg": "port: 7912\n"}))
    return package_path


def _ignore(_phase: dict) -> None:
    return None


def test_an_update_refused_after_it_is_unpacked_keeps_the_working_stock_originals(
    tmp_path: Path,
) -> None:
    plugin_root = tmp_path / "plugins"
    installed = plugin_root / "spoolman"
    (installed / "patches_orig").mkdir(parents=True)
    (installed / "patches_orig" / "printer.cfg").write_text("stock printer config\n")
    (installed / "manifest.json").write_text('{"name": "spoolman", "version": "0.1.0"}')

    result, deferred = batch_one.apply_one(
        plugin_root, {}, _package_the_printer_will_refuse(tmp_path, "spoolman"), {}, _ignore,
    )

    assert result["ok"] is False
    assert "SPOOLMAN_SERVER" in result["reason"]
    assert (installed / "patches_orig" / "printer.cfg").read_text() == "stock printer config\n"
    assert not (installed / "manifest.json").exists()
    assert deferred == []


def test_a_first_install_refused_after_it_is_unpacked_still_leaves_nothing_behind(
    tmp_path: Path,
) -> None:
    """Nothing was on the printer to keep, so the whole extraction goes: left behind, the daemon
    would report a plugin it never applied."""
    plugin_root = tmp_path / "plugins"

    result, _deferred = batch_one.apply_one(
        plugin_root, {}, _package_the_printer_will_refuse(tmp_path, "spoolman"), {}, _ignore,
    )

    assert result["ok"] is False
    assert not (plugin_root / "spoolman").exists()
