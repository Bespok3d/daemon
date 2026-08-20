# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Uninstall's stock-file restore: what core/packages/uninstaller.py and baseline.py must refuse or
survive that the happy-path suite does not reach. Covers a missing stock backup, a stock backup
that changed since it was saved, a symlink destination another installed plugin has since taken
over, a symlink destination the user has since replaced by hand, and a plugin whose manifest is
already gone.

The fixture printer is fake throughout: made-up plugin ids and made-up device paths under tmp_path.
"""

import json
from pathlib import Path

from core.packages import placement, uninstaller


def _write_manifest(plugin_dir: Path, plugin_id: str, install: dict) -> None:
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "manifest.json").write_text(json.dumps({"name": plugin_id, "install": install}))


def test_a_patch_with_no_stock_backup_is_left_on_the_device(tmp_path: Path) -> None:
    """Nothing was ever captured for this target, so uninstall has no safe stock content to put
    back; it must leave the live file exactly as it stands rather than delete or blank it."""
    plugin_root = tmp_path / "plugins"
    device_file = tmp_path / "device" / "moonraker.conf"
    device_file.parent.mkdir(parents=True)
    device_file.write_text("patched moonraker config\n")
    _write_manifest(plugin_root / "orphan-patch", "orphan-patch", {"patches": [{"file": str(device_file)}]})  # noqa: E501

    removed = uninstaller.run_uninstall(plugin_root, "orphan-patch", {})

    assert removed == ["orphan-patch"]
    assert not (plugin_root / "orphan-patch").exists()
    assert device_file.read_text() == "patched moonraker config\n"


def test_a_stock_backup_emptied_since_it_was_saved_still_gets_written_to_the_device(
    tmp_path: Path,
) -> None:
    """The kept backup no longer holds a working file (truncated by some earlier fault, not by this
    plugin's own patch); restore must not carry that loss onto a live, currently-working file."""
    plugin_dir = tmp_path / "plugins" / "corrupt-backup"
    device_file = tmp_path / "device" / "moonraker.conf"
    device_file.parent.mkdir(parents=True)
    device_file.write_text("a working moonraker config\n")
    _write_manifest(plugin_dir, "corrupt-backup", {"patches": [{"file": str(device_file)}]})
    (plugin_dir / "patches_orig").mkdir()
    (plugin_dir / "patches_orig" / "moonraker.conf").write_text("")

    uninstaller.run_uninstall(plugin_dir.parent, "corrupt-backup", {})

    assert device_file.read_text() != ""


def test_a_symlink_taken_over_by_a_later_plugin_is_not_torn_out_from_under_it(
    tmp_path: Path,
) -> None:
    """Plugin B has since wired the same destination Plugin A once owned; removing A must leave B's
    live symlink standing, not clear it back to A's captured stock copy."""
    plugin_root = tmp_path / "plugins"
    device_file = tmp_path / "device" / "shared.cfg"
    device_file.parent.mkdir(parents=True)
    device_file.write_text("stock shared config\n")
    link = [{"from": "conf.cfg", "to": str(device_file)}]
    plugin_a = plugin_root / "plugin-a"
    plugin_a.mkdir(parents=True)
    (plugin_a / "conf.cfg").write_text("plugin a config\n")
    placement.create_symlinks(link, plugin_a, {})
    _write_manifest(plugin_a, "plugin-a", {"symlinks": link})
    plugin_b = plugin_root / "plugin-b"
    plugin_b.mkdir(parents=True)
    (plugin_b / "conf.cfg").write_text("plugin b config\n")
    placement.create_symlinks(link, plugin_b, {})

    uninstaller.run_uninstall(plugin_root, "plugin-a", {})

    assert device_file.is_symlink()
    assert device_file.resolve() == (plugin_b / "conf.cfg").resolve()


def test_a_symlink_the_user_has_since_replaced_by_hand_is_left_alone(tmp_path: Path) -> None:
    """The user removed the plugin's symlink and dropped their own file where it stood; uninstall
    finding the link already gone must never overwrite what the user put in its place."""
    plugin_root = tmp_path / "plugins"
    device_file = tmp_path / "device" / "panel.cfg"
    device_file.parent.mkdir(parents=True)
    device_file.write_text("stock panel config\n")
    plugin_dir = plugin_root / "watcher"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "conf.cfg").write_text("watcher config\n")
    link = [{"from": "conf.cfg", "to": str(device_file)}]
    placement.create_symlinks(link, plugin_dir, {})
    _write_manifest(plugin_dir, "watcher", {"symlinks": link})
    device_file.unlink()
    device_file.write_text("hand-edited by the user\n")

    uninstaller.run_uninstall(plugin_root, "watcher", {})

    assert not device_file.is_symlink()
    assert device_file.read_text() == "hand-edited by the user\n"
