# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Placement: directories, file modes, and resolving the symlink family for the jinni to wire.

A plugin integrates by symlink only (the isolation invariant). The daemon resolves where each placed
file belongs and asks the jinni to WIRE it: creating the device symlink, backing up any stock
original, and recording the reversion is the jinni's actuation (ADR-0037). This module resolves the
(source, destination) pairs from the manifest and the device paths, then delegates the IO. The
stock-original backup contract that lets teardown restore the firmware lives with the actuation in
the jinni (jinni/wiring.py).
"""

from pathlib import Path

from .. import jinni_client
from ..results import item, phase
from .user_vars import expand


def apply_modes(plugin_dir: Path, files: list[dict]) -> dict:
    items: list[dict] = []
    for entry in files:
        path = plugin_dir / entry["path"]
        if path.exists():
            try:
                path.chmod(int(entry["mode"], 8))
                items.append(item(f"{entry['path']} → {entry['mode']}", ok=True))
            except Exception as exc:
                items.append(item(f"{entry['path']}: {exc}", ok=False))
    return phase("modes", "File modes", items)


def create_dirs(dirs: list[str], vars: dict[str, str]) -> dict:
    items: list[dict] = []
    for directory in dirs:
        expanded = expand(directory, vars)
        try:
            Path(expanded).mkdir(parents=True, exist_ok=True)
            items.append(item(expanded, ok=True))
        except Exception as exc:
            items.append(item(f"{expanded}: {exc}", ok=False))
    return phase("dirs", "Directories", items)


def _resolved_link(
    link: dict, plugin_dir: Path, vars: dict[str, str],
) -> tuple[str, dict[str, str]]:
    """The (label, wire request) for one manifest symlink: the source is the placed file in the
    plugin tree, the destination the device path the daemon resolved from it."""
    source = (plugin_dir / link["from"]).resolve()
    destination = Path(expand(link["to"], vars))
    return f"{link['from']} → {destination}", {"source": str(source), "destination": str(destination)}  # noqa: E501


def create_symlinks(symlinks: list[dict], plugin_dir: Path, vars: dict[str, str]) -> dict:
    """Resolve each placed file's symlink and ask the jinni to wire it into the system. The jinni
    creates the device symlink, backs up any stock original, and records the reversion; the daemon
    pairs each result back to its label for the phase log."""
    resolved = [_resolved_link(link, plugin_dir, vars) for link in symlinks]
    results = jinni_client.wire(str(plugin_dir), [request for _label, request in resolved])
    items = [item(label, ok=result.ok, output=result.output)
             for (label, _request), result in zip(resolved, results)]
    return phase("symlinks", "Symlinks", items)


def remove_plugin_symlinks(symlinks: list[dict], plugin_dir: Path, vars: dict[str, str]) -> None:
    """Resolve each symlink's destination and ask the jinni to unwire it (drop the symlink, restore
    any backed-up stock original)."""
    destinations = [str(Path(expand(link["to"], vars))) for link in symlinks]
    if destinations:
        jinni_client.unwire(str(plugin_dir), destinations)


def points_into(link: Path, target_dir: Path) -> bool:
    """True if the symlink resolves to a path inside target_dir (so teardown owns removing it)."""
    try:
        link.resolve().relative_to(target_dir.resolve())
    except (ValueError, OSError):
        return False
    return True


def symlink_owner(link: Path, plugin_root: Path) -> str | None:
    """The plugin id that owns the symlink, by resolving its target under plugin_root. None if the
    path is not a symlink or resolves outside the plugin tree."""
    if not link.is_symlink():
        return None
    try:
        relative = link.resolve().relative_to(plugin_root)
    except (ValueError, OSError):
        return None
    return relative.parts[0] if relative.parts else None
