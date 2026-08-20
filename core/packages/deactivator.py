# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deactivating one plugin, and everything installed that needs it, without removing any files.

Deactivation is the reversible half of removal: the plugin stops affecting the system (its stop
commands run, its symlinks come off, its patched files go back) but its directory stays, so recover
can rebuild it. A plugin other installed plugins depend on strands every one of them the moment it
goes off, so the reference count uninstall answers to applies here too: a deactivate asked for by a
person is refused unless `cascade` takes the dependents with it, while the automatic failure path
cannot refuse (the printer has to boot) and instead takes them along and names each one.

`lifecycle.py` owns the printer-wide off switch, which needs none of this because nothing is left
running to strand. The orchestrator (`core/packages/__init__.py`) owns the plugin root and passes
it in.
"""

from pathlib import Path

from .deactivation import DEACTIVATED_MARKER, deactivate_plugin
from .dependencies import installed_dependents
from .errors import DependentsError
from .plugin_dir import contained_plugin_dir
from .print_guard import guard_no_print_for_removal

REQUESTED_REASON = "deactivated on request"


def _stranded_reason(provider_id: str) -> str:
    return f"deactivated with {provider_id}, the plugin it needs"


def _dependents_still_on(plugin_root: Path, plugin_id: str) -> list[str]:
    """Installed plugins that need this one and are still switched on.

    A dependent that is already off cannot be stranded by this and its own marker already says why
    it went off, most usefully when the safety net put it there: overwriting that with "it went off
    with its provider" would throw away the diagnosis of the actual failure.
    """
    dependents = installed_dependents(plugin_root, plugin_id)
    return [dependent_id for dependent_id in dependents
            if not (plugin_root / dependent_id / DEACTIVATED_MARKER).exists()]


def _deactivate_dependents_first(plugin_root: Path, plugin_id: str, dependents: list[str],
                                 vars: dict[str, str], reason: str) -> list[str]:
    """Take the dependents off before the plugin they need, so nothing is left running against a
    provider that has already gone. Each dependent's own marker says whose fall took it down, so a
    user reading one plugin's state is never left guessing why it stopped."""
    for dependent_id in dependents:
        deactivate_plugin(plugin_root / dependent_id, vars, _stranded_reason(plugin_id))
    deactivate_plugin(plugin_root / plugin_id, vars, reason)
    return [*dependents, plugin_id]


def deactivate_with_dependents(plugin_root: Path, plugin_id: str, vars: dict[str, str],
                               reason: str) -> list[str]:
    """Deactivate the plugin together with every installed plugin that needs it, dependents first.

    This is the path that cannot say no: the printer has to come back up, so the automatic safety
    net uses it and reports every id it returns rather than refusing and leaving Klipper down.
    """
    dependents = _dependents_still_on(plugin_root, plugin_id)
    return _deactivate_dependents_first(plugin_root, plugin_id, dependents, vars, reason)


def run_deactivate(plugin_root: Path, plugin_id: str, vars: dict[str, str],
                   cascade: bool = False) -> list[str]:
    """Deactivate a plugin, keeping its files. Refuses while installed dependents need it, unless
    cascade deactivates them too. Returns the ids deactivated, dependents first, target last.

    A plugin that is not installed is already in the state the caller asked for, so it reports
    nothing deactivated instead of failing: a second click must never leave the caller stuck on an
    error it cannot act on. That is the answer uninstall gives for the same case.
    """
    plugin_dir = contained_plugin_dir(plugin_root, plugin_id)
    if not plugin_dir.exists():
        return []
    dependents = _dependents_still_on(plugin_root, plugin_id)
    if dependents and not cascade:
        raise DependentsError(plugin_id, dependents)
    guard_no_print_for_removal(plugin_root, [plugin_id, *dependents])
    return _deactivate_dependents_first(plugin_root, plugin_id, dependents, vars, REQUESTED_REASON)
