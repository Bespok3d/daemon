# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reading installed plugins' manifests off disk: read one plugin's manifest.json, and enumerate
the installed plugins (the directories under the plugin root that carry a manifest)."""

import json
from pathlib import Path
from typing import cast

from .manifest_warnings import note_torn_plugin


def manifest_at(plugin_dir: Path) -> dict:
    return cast(dict, json.loads((plugin_dir / "manifest.json").read_text()))


def installed_manifest_dirs(plugin_root: Path) -> list[Path]:
    if not plugin_root.exists():
        return []
    return [
        plugin_dir for plugin_dir in sorted(plugin_root.iterdir())
        if plugin_dir.is_dir() and (plugin_dir / "manifest.json").exists()
    ]


def readable_manifest(plugin_dir: Path) -> dict | None:
    """One plugin's manifest, or None when it cannot be read: absent, half written by a power cut,
    or holding something that is not a manifest. A plugin whose manifest is unreadable still has to
    be removable and still has to be switchable off, so every path that must survive one asks here
    instead of reading the file itself. An operation collecting torn plugins is told which plugin
    this was and what went wrong with it, so a skip made here is never a silent one."""
    try:
        manifest = json.loads((plugin_dir / "manifest.json").read_text())
    except (OSError, ValueError) as unreadable:
        note_torn_plugin(plugin_dir, f"{type(unreadable).__name__}: {unreadable}")
        return None
    if isinstance(manifest, dict):
        return manifest
    note_torn_plugin(plugin_dir, f"manifest.json holds a {type(manifest).__name__}, not a manifest")
    return None
