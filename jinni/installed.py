"""Enumerate what is installed under the bespok3d plugin root: the installed plugins and which the
safety net (or the user) turned off. Pure filesystem reads over the plugin tree, so they live in
their own leaf rather than in the Jinni interface; the base Jinni's `installed_plugins` /
`deactivated_plugins` methods pass it the resolved plugin root.
"""
import json
from pathlib import Path


def list_installed(plugin_root: Path) -> dict[str, str]:
    if not plugin_root.is_dir():
        return {}
    installed: dict[str, str] = {}
    for plugin_dir in plugin_root.iterdir():
        manifest = plugin_dir / "manifest.json"
        if plugin_dir.is_dir() and manifest.exists():
            installed[plugin_dir.name] = json.loads(manifest.read_text()).get("version", "")
    return installed


def list_deactivated(plugin_root: Path) -> list[str]:
    """Installed plugins whose dir carries a deactivated.json marker. The app shows these as
    disabled, not installed-and-working."""
    if not plugin_root.is_dir():
        return []
    return sorted(
        plugin_dir.name for plugin_dir in plugin_root.iterdir()
        if (plugin_dir / "deactivated.json").exists()
    )
