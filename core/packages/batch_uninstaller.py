"""Removing several plugins in one go, restarting affected services only once at the end.

Mirrors the batched update (updater.py) for the removal path: each selected plugin's effect is taken
off the system with its core-service restart DEFERRED, the deduped restarts run once, then Klipper
and Moonraker are awaited healthy. A plugin still depended on by an installed plugin OUTSIDE the
selection refuses the batch unless `cascade` removes those dependents too. One plugin's removal
failure is contained so the rest of the batch still completes.
"""

from pathlib import Path

from ..safety import OperationContext, OperationKind
from .dependencies import installed_dependents
from .errors import DependentsError
from .print_guard import guard_no_print_for_removal
from .recovery import restart_services
from .uninstaller import removal_restart_commands, remove_with_dependents


def _collect_removal_closure(plugin_root: Path, plugin_id: str, closure: list[str]) -> None:
    """Append a plugin and all its transitive installed dependents to `closure`, dependents first:
    every plugin that removing this one would take with it."""
    for dependent in installed_dependents(plugin_root, plugin_id):
        if dependent not in closure:
            _collect_removal_closure(plugin_root, dependent, closure)
    if plugin_id not in closure:
        closure.append(plugin_id)


def _uninstall_one(plugin_root: Path, plugin_id: str, vars: dict[str, str], removed: list[str]) -> dict:  # noqa: E501
    """Remove one selected plugin (and any not-yet-removed dependents) WITHOUT restarting, contained
    so one plugin's failure does not abort the batch. Returns the per-plugin result."""
    if not (plugin_root / plugin_id).exists():
        return {"plugin_id": plugin_id, "ok": True, "skipped": True, "reason": "not installed", "log": []}  # noqa: E501
    try:
        remove_with_dependents(plugin_root, plugin_id, vars, removed)
    except Exception as exc:  # noqa: BLE001 - one plugin's removal error must NOT abort the batch
        return {"plugin_id": plugin_id, "ok": False, "skipped": False, "reason": f"uninstall error: {type(exc).__name__}: {exc}", "log": []}  # noqa: E501
    return {"plugin_id": plugin_id, "ok": True, "skipped": False, "reason": "", "log": []}


def run_uninstall_batch(plugin_root: Path, plugin_ids: list[str], vars: dict[str, str], cascade: bool = False) -> list[dict]:  # noqa: E501
    """Remove the given plugins: per-plugin results then a final (services) restart result."""
    present = [plugin_id for plugin_id in plugin_ids if (plugin_root / plugin_id).exists()]
    if not present:
        return []
    closure: list[str] = []
    for plugin_id in present:
        _collect_removal_closure(plugin_root, plugin_id, closure)
    external = [plugin_id for plugin_id in closure if plugin_id not in present]
    if external and not cascade:
        raise DependentsError(present[0], external)
    guard_no_print_for_removal(plugin_root, closure)
    restart_commands = removal_restart_commands(plugin_root, closure, vars)
    removed: list[str] = []
    results: list[dict] = []
    for plugin_id in present:
        results.append(_uninstall_one(plugin_root, plugin_id, vars, removed))
    if restart_commands:
        only = present[0] if len(present) == 1 else None
        ctx = OperationContext(OperationKind.UNINSTALL, plugin_id=only)
        results.append(restart_services(plugin_root, restart_commands, vars, ctx))
    return results
