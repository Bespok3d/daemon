# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A printer holds more than one file of a given name, and a plugin may patch two of them.

Keyed by the bare file name, the second file's original was never captured (a copy of that name was
already there) and the first file's original was written back over both of them on uninstall. These
guard the fix: one kept original per file, and the copies an earlier daemon left under the bare name
still restore.

The fixture printer is fake throughout: made-up device paths under tmp_path, no real device path.
"""

from pathlib import Path

from core.packages import baseline, patches

MOONRAKER_STOCK = "[server]\nport: 7125\n"
KLIPPER_STOCK = "[server]\nport: 7126\n"
PORT_FRAGMENT = (
    "--- a/config.conf\n+++ b/config.conf\n@@ -1,2 +1,2 @@\n"
    " [server]\n-port: 7125\n+port: 8125\n"
)
OTHER_PORT_FRAGMENT = (
    "--- a/config.conf\n+++ b/config.conf\n@@ -1,2 +1,2 @@\n"
    " [server]\n-port: 7126\n+port: 8126\n"
)


def _printer_with_two_config_files(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A plugin patching `moonraker/config.conf` and `klipper/config.conf`: same name, two files."""
    plugin_dir = tmp_path / "plugins" / "two-configs"
    (plugin_dir / "patches").mkdir(parents=True)
    (plugin_dir / "patches" / "01-moonraker.patch").write_text(PORT_FRAGMENT)
    (plugin_dir / "patches" / "02-klipper.patch").write_text(OTHER_PORT_FRAGMENT)
    moonraker_config = tmp_path / "device" / "moonraker" / "config.conf"
    klipper_config = tmp_path / "device" / "klipper" / "config.conf"
    moonraker_config.parent.mkdir(parents=True)
    klipper_config.parent.mkdir(parents=True)
    moonraker_config.write_text(MOONRAKER_STOCK)
    klipper_config.write_text(KLIPPER_STOCK)
    return plugin_dir, moonraker_config, klipper_config


def _patch_defs(moonraker_config: Path, klipper_config: Path) -> list[dict]:
    return [
        {"file": str(moonraker_config), "patch": "patches/01-moonraker.patch"},
        {"file": str(klipper_config), "patch": "patches/02-klipper.patch"},
    ]


def test_each_patched_file_keeps_its_own_original(tmp_path: Path) -> None:
    plugin_dir, moonraker_config, klipper_config = _printer_with_two_config_files(tmp_path)

    result = patches.apply_patches(_patch_defs(moonraker_config, klipper_config), plugin_dir, {})

    assert result["ok"] is True
    kept = baseline.stock_copies(plugin_dir)
    assert baseline.kept_original(kept, moonraker_config).read_text() == MOONRAKER_STOCK
    assert baseline.kept_original(kept, klipper_config).read_text() == KLIPPER_STOCK


def test_both_files_are_patched_from_their_own_content(tmp_path: Path) -> None:
    """Given one shared original, the second file was patched from the first file's text."""
    plugin_dir, moonraker_config, klipper_config = _printer_with_two_config_files(tmp_path)

    patches.apply_patches(_patch_defs(moonraker_config, klipper_config), plugin_dir, {})

    assert moonraker_config.read_text() == "[server]\nport: 8125\n"
    assert klipper_config.read_text() == "[server]\nport: 8126\n"


def test_uninstall_puts_each_file_back_the_way_it_was(tmp_path: Path) -> None:
    """The failure this exists for: the user removes the plugin and Klipper comes back holding
    Moonraker's config, because both files restored from the one kept copy."""
    plugin_dir, moonraker_config, klipper_config = _printer_with_two_config_files(tmp_path)
    patch_defs = _patch_defs(moonraker_config, klipper_config)
    patches.apply_patches(patch_defs, plugin_dir, {})

    patches.restore_original_files(patch_defs, baseline.stock_copies(plugin_dir), {})

    assert moonraker_config.read_text() == MOONRAKER_STOCK
    assert klipper_config.read_text() == KLIPPER_STOCK


def test_a_copy_an_earlier_daemon_kept_under_the_bare_name_still_restores(tmp_path: Path) -> None:
    """A printer patched before this daemon holds one copy named `config.conf`, and that copy is the
    only record of the stock file. Updating the daemon must keep restoring from it."""
    plugin_dir, moonraker_config, _klipper = _printer_with_two_config_files(tmp_path)
    kept = baseline.stock_copies(plugin_dir)
    kept.mkdir(parents=True)
    (kept / "config.conf").write_text(MOONRAKER_STOCK)
    moonraker_config.write_text("[server]\nport: 8125\n")
    patch_defs = [{"file": str(moonraker_config), "patch": "patches/01-moonraker.patch"}]

    patches.restore_original_files(patch_defs, kept, {})

    assert moonraker_config.read_text() == MOONRAKER_STOCK


def test_a_re_apply_reuses_the_copy_kept_under_the_bare_name(tmp_path: Path) -> None:
    """The old copy is the baseline the re-apply patches from, so an update on a printer holding one
    does not re-capture an already patched file as its stock original."""
    plugin_dir, moonraker_config, _klipper = _printer_with_two_config_files(tmp_path)
    kept = baseline.stock_copies(plugin_dir)
    kept.mkdir(parents=True)
    (kept / "config.conf").write_text(MOONRAKER_STOCK)
    moonraker_config.write_text("[server]\nport: 8125\n")

    result = patches.apply_patches(
        [{"file": str(moonraker_config), "patch": "patches/01-moonraker.patch"}], plugin_dir, {},
    )

    assert result["ok"] is True
    assert (kept / "config.conf").read_text() == MOONRAKER_STOCK
    assert not (kept / "device").exists()
