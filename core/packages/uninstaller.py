# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Uninstalling a plugin: take its effect off the system and restart the services its removal needs.

Removal is reference-counted and cascades dependents-first: a plugin that other installed plugins
still depend on is refused unless `cascade` removes them too. Taking a plugin off the system runs
its stop commands, removes its symlinks, restores any files it patched, drops its baked-dep links
and venv, and deletes its directory. Install runs a plugin's `restart` hooks so its config takes
effect; uninstall runs the same hooks so the REMOVAL takes effect (Klipper keeps a now-deleted
[section] loaded, and nginx a removed web location, until the service restarts).

The orchestrator (`core/packages/__init__.py`) owns the plugin root and passes it in.
"""

import shutil
from pathlib import Path

from .. import jinni_client
from ..intent import normalize_install
from ..safety import OperationContext, OperationKind
from .deactivation import run_stop_commands
from .dependencies import installed_dependents
from .errors import DependentsError
from .manifest import manifest_at
from .patches import restore_original_files
from .placement import remove_plugin_symlinks
from .plugin_dir import contained_plugin_dir
from .plugin_venv import remove_plugin_venv
from .print_guard import guard_no_print_for_removal
from .python_deps import remove_plugin_site_links
from .recovery import restart_services
from .user_vars import expand, load_user_vars


def _uninstall_from_manifest(plugin_dir: Path, vars: dict[str, str]) -> None:
    manifest = manifest_at(plugin_dir)
    install_spec = normalize_install(manifest.get("install", {}), jinni_client.variant_facts())
    full_vars = {**vars, **load_user_vars(plugin_dir)}
    run_stop_commands(install_spec["stops"] + manifest.get("stop", []), full_vars)
    remove_plugin_symlinks(install_spec["symlinks"], plugin_dir, full_vars)
    restore_original_files(install_spec["patches"], plugin_dir / "patches_orig", full_vars)


def _remove_one(plugin_dir: Path, vars: dict[str, str]) -> None:
    if (plugin_dir / "manifest.json").exists():
        _uninstall_from_manifest(plugin_dir, vars)
    remove_plugin_site_links(plugin_dir, vars)
    remove_plugin_venv(plugin_dir.name, vars)
    shutil.rmtree(plugin_dir)


def remove_with_dependents(plugin_root: Path, plugin_id: str, vars: dict[str, str], removed: list[str]) -> None:  # noqa: E501
    """Remove a plugin and its installed dependents, dependents first, appending each removed id to
    `removed` (which dedupes across calls). Public so the batch path reuses one removal walk."""
    plugin_dir = contained_plugin_dir(plugin_root, plugin_id)
    for dependent in installed_dependents(plugin_root, plugin_id):
        if dependent not in removed:
            remove_with_dependents(plugin_root, dependent, vars, removed)
    if plugin_dir.exists() and plugin_id not in removed:
        _remove_one(plugin_dir, vars)
        removed.append(plugin_id)


def _manifest_restart_commands(manifest: dict, vars: dict[str, str]) -> list[str]:
    """The restart hooks one manifest declares, resolved to expanded shell commands. A hook the
    device does not recognize is skipped: removal is lenient, never refused over an unknown hook."""
    hooks = manifest.get("install", {}).get("restart", [])
    commands = [jinni_client.restart_command(hook) for hook in hooks]
    return [expand(command, vars) for command in commands if command is not None]


def removal_restart_commands(plugin_root: Path, plugin_ids: list[str], vars: dict[str, str]) -> list[str]:  # noqa: E501
    """The core-service restart hooks the plugins being removed declare, expanded and deduped.

    Public so the batch path collects each plugin's restart hooks before any dir is gone."""
    commands: list[str] = []
    for plugin_id in plugin_ids:
        plugin_dir = contained_plugin_dir(plugin_root, plugin_id)
        if (plugin_dir / "manifest.json").exists():
            commands.extend(_manifest_restart_commands(manifest_at(plugin_dir), vars))
    return list(dict.fromkeys(commands))


def remove_all_plugins(plugin_root: Path, vars: dict[str, str]) -> list[str]:
    """Remove every plugin's effect and files WITHOUT restarting, returning the deduped core-service
    restart commands so the caller restarts ONCE after everything is gone. teardown's path: removing
    each plugin through run_uninstall bounced Klipper/Moonraker per plugin and waited on health each
    pass (the restart storm). Collect the restart hooks up front (the manifests are read before the
    dirs are deleted), then remove unconditionally (a full teardown takes everything, so dependents
    and conflicts are moot); best-effort so one bad plugin never strands the rest."""
    if not plugin_root.exists():
        return []
    plugin_ids = [plugin_dir.name for plugin_dir in plugin_root.iterdir() if plugin_dir.is_dir()]
    restart_commands = removal_restart_commands(plugin_root, plugin_ids, vars)
    for plugin_id in plugin_ids:
        try:
            _remove_one(plugin_root / plugin_id, vars)
        except Exception:  # noqa: BLE001  teardown is best-effort: keep removing the rest
            pass
    return restart_commands


def run_uninstall(plugin_root: Path, plugin_id: str, vars: dict[str, str], cascade: bool = False) -> list[str]:  # noqa: E501
    """Remove a plugin. Refuses if installed dependents need it, unless cascade removes them too.

    Returns the ids removed, dependents first, target last.
    """
    plugin_dir = contained_plugin_dir(plugin_root, plugin_id)
    if not plugin_dir.exists():
        raise FileNotFoundError(plugin_id)
    dependents = installed_dependents(plugin_root, plugin_id)
    if dependents and not cascade:
        raise DependentsError(plugin_id, dependents)
    guard_no_print_for_removal(plugin_root, [plugin_id, *dependents])
    restart_commands = removal_restart_commands(plugin_root, [*dependents, plugin_id], vars)
    removed: list[str] = []
    remove_with_dependents(plugin_root, plugin_id, vars, removed)
    if restart_commands:
        restart_services(plugin_root, restart_commands, vars, OperationContext(OperationKind.UNINSTALL, plugin_id))  # noqa: E501
    return removed
