# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Printer-level problems: the conditions that make a printer work at all, plugin or no plugin.

A printer holding zero plugins can still be broken. The include lines its own config needs before it
loads anything of ours can be gone, the bespok3d tree can be missing a directory, a plugin can be
left half removed by an interrupted uninstall. None of those belong to a plugin, so none of them fit
a per-plugin drift report, and a check that only walks installed plugins calls such a printer
healthy.

What "correct" means here follows the user's last intent, which is the global deactivated marker:
with it absent the wiring is meant to be in place, with it present the wiring is meant to be gone
and wiring still there is itself the problem. Read-only; never mutates.
"""
from pathlib import Path
from typing import Any

from .. import jinni_client
from ..data_root import PLUGIN_ROOT_RELATIVE, REQUIRED_DIRECTORIES
from ..packages.deactivation import DEACTIVATED_MARKER, RECOVERY_FAILURE_MARKER
from ..packages.lifecycle import GLOBAL_DEACTIVATED_MARKER

PROBLEM_INCLUDES_MISSING = "includes_missing"
PROBLEM_INCLUDES_PRESENT_WHILE_OFF = "includes_present_while_off"
PROBLEM_DIRECTORY_MISSING = "directory_missing"
PROBLEM_PLUGIN_HALF_REMOVED = "plugin_half_removed"
PROBLEM_PLUGIN_RECOVERY_FAILED = "plugin_recovery_failed"


def _problem(kind: str, detail: str, plugin_id: str | None = None) -> dict[str, Any]:
    return {"kind": kind, "detail": detail, "plugin_id": plugin_id}


def is_switched_off(data_root: Path) -> bool:
    """True when the user asked for bespok3d to be off. Every expectation below flips on this."""
    return (data_root / GLOBAL_DEACTIVATED_MARKER).exists()


def _include_problems(switched_off: bool) -> list[dict[str, Any]]:
    status = jinni_client.bespok3d_include_status()
    if switched_off:
        return [_problem(PROBLEM_INCLUDES_PRESENT_WHILE_OFF, config_name)
                for config_name, present in sorted(status.items()) if present]
    return [_problem(PROBLEM_INCLUDES_MISSING, config_name)
            for config_name, present in sorted(status.items()) if not present]


def _directory_problems(data_root: Path) -> list[dict[str, Any]]:
    return [_problem(PROBLEM_DIRECTORY_MISSING, relative)
            for relative in REQUIRED_DIRECTORIES if not (data_root / relative).is_dir()]


def _one_plugin_problem(plugin_dir: Path) -> dict[str, Any] | None:
    if not (plugin_dir / "manifest.json").exists():
        return _problem(PROBLEM_PLUGIN_HALF_REMOVED, plugin_dir.name, plugin_dir.name)
    if (plugin_dir / DEACTIVATED_MARKER).exists():
        return None
    if (plugin_dir / RECOVERY_FAILURE_MARKER).exists():
        return _problem(PROBLEM_PLUGIN_RECOVERY_FAILED, plugin_dir.name, plugin_dir.name)
    return None


def _plugin_problems(plugin_root: Path) -> list[dict[str, Any]]:
    """A plugin left without its manifest is the wreckage of an uninstall that stopped partway; a
    plugin still carrying its failure marker never finished coming back. The safety net's own
    deactivated plugins are not counted: those are a settled state the user can see and act on."""
    if not plugin_root.is_dir():
        return []
    found = [_one_plugin_problem(plugin_dir)
             for plugin_dir in sorted(plugin_root.iterdir()) if plugin_dir.is_dir()]
    return [problem for problem in found if problem is not None]


def printer_problems(data_root: Path) -> list[dict[str, Any]]:
    """Everything wrong with the printer itself, in the order a user would fix it."""
    switched_off = is_switched_off(data_root)
    return [
        *_include_problems(switched_off),
        *_directory_problems(data_root),
        *_plugin_problems(data_root / PLUGIN_ROOT_RELATIVE),
    ]
