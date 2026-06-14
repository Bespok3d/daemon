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

from ..intent import RESTART_HOOKS, normalize_install
from ..safety import OperationContext, OperationKind
from .deactivation import run_stop_commands
from .dependencies import installed_dependents
from .errors import DependentsError
from .manifest import manifest_at
from .patches import restore_original_files
from .placement import remove_plugin_symlinks
from .print_guard import guard_no_print_for_removal
from .python_deps import remove_plugin_site_links, remove_plugin_venv
from .recovery import restart_services
from .user_vars import expand, load_user_vars


def _uninstall_from_manifest(plugin_dir: Path, vars: dict[str, str]) -> None:
    manifest = manifest_at(plugin_dir)
    install_spec = normalize_install(manifest.get("install", {}))
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


def _remove_with_dependents(plugin_root: Path, plugin_id: str, vars: dict[str, str], removed: list[str]) -> None:  # noqa: E501
    for dependent in installed_dependents(plugin_root, plugin_id):
        if dependent not in removed:
            _remove_with_dependents(plugin_root, dependent, vars, removed)
    plugin_dir = plugin_root / plugin_id
    if plugin_dir.exists() and plugin_id not in removed:
        _remove_one(plugin_dir, vars)
        removed.append(plugin_id)


def _manifest_restart_commands(manifest: dict, vars: dict[str, str]) -> list[str]:
    """The restart hooks one manifest declares, resolved to expanded shell commands."""
    hooks = manifest.get("install", {}).get("restart", [])
    return [expand(RESTART_HOOKS[hook], vars) for hook in hooks if hook in RESTART_HOOKS]


def _removal_restart_commands(plugin_root: Path, plugin_ids: list[str], vars: dict[str, str]) -> list[str]:  # noqa: E501
    """The core-service restart hooks the plugins being removed declare, expanded and deduped."""
    commands: list[str] = []
    for plugin_id in plugin_ids:
        plugin_dir = plugin_root / plugin_id
        if (plugin_dir / "manifest.json").exists():
            commands.extend(_manifest_restart_commands(manifest_at(plugin_dir), vars))
    return list(dict.fromkeys(commands))


def run_uninstall(plugin_root: Path, plugin_id: str, vars: dict[str, str], cascade: bool = False) -> list[str]:  # noqa: E501
    """Remove a plugin. Refuses if installed dependents need it, unless cascade removes them too.

    Returns the ids removed, dependents first, target last.
    """
    plugin_dir = plugin_root / plugin_id
    if not plugin_dir.exists():
        raise FileNotFoundError(plugin_id)
    dependents = installed_dependents(plugin_root, plugin_id)
    if dependents and not cascade:
        raise DependentsError(plugin_id, dependents)
    guard_no_print_for_removal(plugin_root, [plugin_id, *dependents])
    restart_commands = _removal_restart_commands(plugin_root, [*dependents, plugin_id], vars)
    removed: list[str] = []
    _remove_with_dependents(plugin_root, plugin_id, vars, removed)
    if restart_commands:
        restart_services(plugin_root, restart_commands, vars, OperationContext(OperationKind.UNINSTALL, plugin_id))  # noqa: E501
    return removed
