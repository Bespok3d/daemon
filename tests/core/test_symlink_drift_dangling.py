# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Symlink drift: the one case test_selfcheck.py's plugin-level tests do not reach.

A symlink that was made correctly, pointing at the exact path the manifest expects, but whose
target file has since been removed, is a plugin that fails to load on the next reboot: the module's
own docstring calls that "exactly like a missing symlink". Comparing the recorded path string from
os.readlink to the expected path never notices this, because the string still matches; only checking
whether that target actually exists on disk would catch it.
"""
import json
from pathlib import Path

from core.selfcheck import symlink_drift


def _plugin_with_correct_but_dangling_symlink(plugin_root: Path, link_path: Path) -> Path:
    """A plugin whose symlink was made correctly and then had its own source file removed out from
    under it, the way a half finished uninstall or a wiped overlay leaves things."""
    plugin_dir = plugin_root / "dangling-plugin"
    source_file = plugin_dir / "files" / "mod.py"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("# source\n")
    manifest = {
        "name": "dangling-plugin",
        "install": {"symlinks": [{"from": "files/mod.py", "to": str(link_path)}]},
    }
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest))
    link_path.parent.mkdir(parents=True)
    link_path.symlink_to(source_file.resolve())
    source_file.unlink()
    return plugin_dir


def test_plugin_drift_reports_a_symlink_whose_target_was_removed_after_it_was_made(
    tmp_path: Path,
) -> None:
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    link_path = tmp_path / "extras" / "mod.py"
    plugin_dir = _plugin_with_correct_but_dangling_symlink(plugin_root, link_path)

    report = symlink_drift.plugin_drift(plugin_dir, {})

    assert report is not None
    assert report["plugin_id"] == "dangling-plugin"
    assert report["symlink_issues"] != []
