# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Self-check: does this printer actually work, and does it match what the user last asked for.

Two questions, answered together. `printer_state` asks whether the printer itself is sound (its own
config still includes us, the bespok3d tree is whole, no plugin left half removed), and
`symlink_drift` asks whether each installed plugin's links are where its manifest says. A printer
with no plugins left has nothing to drift and can still be thoroughly broken, so the first question
is asked whatever the second one finds.

Read-only; never mutates. Every problem it can report is one `recover` puts right.

Scope: links, wiring and tree shape. Patches and templates are harder to verify cheaply.
"""
from pathlib import Path
from typing import Any

from .. import jinni_client
from ..data_root import PLUGIN_ROOT_RELATIVE
from . import printer_state
from .printer_state import (  # noqa: F401  re-export: the vocabulary of a printer-level problem
    PROBLEM_DIRECTORY_MISSING,
    PROBLEM_INCLUDES_MISSING,
    PROBLEM_INCLUDES_PRESENT_WHILE_OFF,
    PROBLEM_PLUGIN_HALF_REMOVED,
    PROBLEM_PLUGIN_RECOVERY_FAILED,
    printer_problems,
)
from .symlink_drift import (  # noqa: F401  re-export: the vocabulary of a link issue
    ISSUE_MISSING,
    ISSUE_NOT_A_SYMLINK,
    ISSUE_WRONG_TARGET,
    plugin_drift,
)

_DEACTIVATED_MARKER = "deactivated.json"


def _checkable_plugin_dirs(plugin_root: Path) -> list[Path]:
    """Plugins whose links are expected to be in place: the ones the user has not switched off, and
    only while bespok3d itself is on. A switched-off printer is unlinked on purpose."""
    if not plugin_root.is_dir():
        return []
    return [plugin_dir for plugin_dir in sorted(plugin_root.iterdir())
            if plugin_dir.is_dir() and not (plugin_dir / _DEACTIVATED_MARKER).exists()]


def _drift_reports(data_root: Path, vars: dict[str, str]) -> list[dict[str, Any]]:
    if printer_state.is_switched_off(data_root):
        return []
    plugin_dirs = _checkable_plugin_dirs(data_root / PLUGIN_ROOT_RELATIVE)
    found = [plugin_drift(plugin_dir, vars) for plugin_dir in plugin_dirs]
    return [report for report in found if report is not None]


def _reboot_required() -> list[str]:
    """What the printer says only a power cycle will clear. A jinni older than this daemon has never
    heard the question, and that is "nothing to report", never a reason to lose the whole self-check
    for a printer that is otherwise answering."""
    try:
        return jinni_client.reboot_required()
    except Exception:  # noqa: BLE001  an unanswered question is not a finding
        return []


def run_selfcheck(vars: dict[str, str]) -> dict[str, Any]:
    """The printer's problems, its plugins' drift, and whether bespok3d is switched off at all.

    Switched off is reported even though it is nobody's fault: a printer whose wiring is gone on
    purpose looks identical to a broken one from the outside, and a caller that cannot tell them
    apart shows nothing and offers no way back. A state to display, never a problem to fix.
    """
    data_root = Path(vars["BESPOK3D"])
    return {
        "switched_off": printer_state.is_switched_off(data_root),
        "reboot_required": _reboot_required(),
        "problems": printer_problems(data_root),
        "drift": _drift_reports(data_root, vars),
    }
