"""Reading installed plugins' manifests off disk: read one plugin's manifest.json, and enumerate
the installed plugins (the directories under the plugin root that carry a manifest)."""

import json
from pathlib import Path
from typing import cast


def manifest_at(plugin_dir: Path) -> dict:
    return cast(dict, json.loads((plugin_dir / "manifest.json").read_text()))


def installed_manifest_dirs(plugin_root: Path) -> list[Path]:
    if not plugin_root.exists():
        return []
    return [
        plugin_dir for plugin_dir in sorted(plugin_root.iterdir())
        if plugin_dir.is_dir() and (plugin_dir / "manifest.json").exists()
    ]
