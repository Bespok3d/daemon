# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Edge cases the happy-path patch suite (test_packages_patches.py) does not cover: what
core.packages.patches must refuse before writing anything, and what it must survive intact. The
governing invariant is that a patch that cannot apply cleanly is refused before any write, never
applied partway, and a reversal gives back exactly what was there before.
"""
from pathlib import Path

from core.packages import patches

STOCK = "alpha\nbeta\ngamma\ndelta\nepsilon\n"
PATCHED = "alpha\nbeta2\ngamma\ndelta\nepsilon\n"
BETA_FRAGMENT = (
    "--- a/mod.py\n+++ b/mod.py\n@@ -1,5 +1,5 @@\n"
    " alpha\n-beta\n+beta2\n gamma\n delta\n epsilon\n"
)
INCOMPATIBLE_FRAGMENT = (
    "--- a/mod.py\n+++ b/mod.py\n@@ -10,3 +10,3 @@\n"
    " zeta\n-omega\n+omega2\n theta\n"
)


def test_apply_patches_refuses_a_missing_target_before_writing_anything(tmp_path: Path) -> None:
    """The device file to patch does not exist: every fragment is refused and nothing is written,
    never a fabricated baseline or a fabricated target."""
    plugin_dir = tmp_path / "plugin"
    fragment_dir = plugin_dir / "patches"
    fragment_dir.mkdir(parents=True)
    (fragment_dir / "01-beta.patch").write_text(BETA_FRAGMENT)
    target = tmp_path / "klippy" / "mod.py"
    patch_defs = [{"file": str(target), "patch": "patches/01-beta.patch"}]

    result = patches.apply_patches(patch_defs, plugin_dir, {})

    assert result["ok"] is False
    assert "not found" in result["items"][0]["output"]
    assert not target.exists()
    assert not (plugin_dir / "patches_orig" / "mod.py").exists()


def test_apply_patches_leaves_the_device_untouched_when_a_later_fragment_fails(
    tmp_path: Path,
) -> None:
    """Two fragments target one file: the first applies cleanly, the second does not fit at all.
    The whole group must be refused before any write, so the device file still holds exactly what
    it held before this call rather than a partway result the caller was told failed."""
    plugin_dir = tmp_path / "plugin"
    fragment_dir = plugin_dir / "patches"
    fragment_dir.mkdir(parents=True)
    (fragment_dir / "01-beta.patch").write_text(BETA_FRAGMENT)
    (fragment_dir / "02-incompatible.patch").write_text(INCOMPATIBLE_FRAGMENT)
    target = tmp_path / "klippy" / "mod.py"
    target.parent.mkdir(parents=True)
    target.write_text(STOCK)
    patch_defs = [
        {"file": str(target), "patch": "patches/01-beta.patch"},
        {"file": str(target), "patch": "patches/02-incompatible.patch"},
    ]

    result = patches.apply_patches(patch_defs, plugin_dir, {})

    assert result["ok"] is False
    assert target.read_text() == STOCK


def test_apply_patches_survives_an_empty_patch_fragment(tmp_path: Path) -> None:
    """A patch fragment with no hunks at all must be a harmless no-op, not a crash or a corrupted
    write to the device file."""
    plugin_dir = tmp_path / "plugin"
    fragment_dir = plugin_dir / "patches"
    fragment_dir.mkdir(parents=True)
    (fragment_dir / "01-empty.patch").write_text("")
    target = tmp_path / "klippy" / "mod.py"
    target.parent.mkdir(parents=True)
    target.write_text(STOCK)
    patch_defs = [{"file": str(target), "patch": "patches/01-empty.patch"}]

    result = patches.apply_patches(patch_defs, plugin_dir, {})

    assert result["ok"] is True
    assert target.read_text() == STOCK


def test_apply_patches_patches_through_a_symlink_target_without_replacing_it(
    tmp_path: Path,
) -> None:
    """The Klipper file being patched can itself be a symlink another plugin placed there (the
    isolation invariant). Patching it must write through the link, never replace it with a plain
    file, or the owning plugin's placement breaks."""
    plugin_dir = tmp_path / "plugin"
    fragment_dir = plugin_dir / "patches"
    fragment_dir.mkdir(parents=True)
    (fragment_dir / "01-beta.patch").write_text(BETA_FRAGMENT)
    owned_file = tmp_path / "other_plugin" / "mod.py"
    owned_file.parent.mkdir(parents=True)
    owned_file.write_text(STOCK)
    target = tmp_path / "klippy" / "mod.py"
    target.parent.mkdir(parents=True)
    target.symlink_to(owned_file)
    patch_defs = [{"file": str(target), "patch": "patches/01-beta.patch"}]

    result = patches.apply_patches(patch_defs, plugin_dir, {})

    assert result["ok"] is True
    assert target.is_symlink()
    assert target.resolve() == owned_file.resolve()
    assert owned_file.read_text() == PATCHED


def test_restore_original_files_is_a_safe_no_op_without_a_captured_baseline(tmp_path: Path) -> None:
    """Teardown can run against a plugin whose install failed before any baseline was ever captured
    (patches_orig never created). Restoring must leave whatever is on disk alone: no crash, and no
    fabricated original it never actually held."""
    orig_dir = tmp_path / "plugin" / "patches_orig"
    target = tmp_path / "klippy" / "mod.py"
    target.parent.mkdir(parents=True)
    target.write_text("content nobody patched\n")

    patches.restore_original_files([{"file": str(target)}], orig_dir, {})

    assert target.read_text() == "content nobody patched\n"
    assert not orig_dir.exists()
