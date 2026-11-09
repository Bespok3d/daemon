# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The narrow repair: put the printer's own setup right without re-applying a single plugin.

A printer that lost only its include lines used to get the full recover, every plugin re-applied
and every service restarted, for what is a two-line config fix. This repair runs when selfcheck
proves the fault is setup only, and refuses otherwise, so it can never hide damage that needs the
full recover. The caller reboots the printer once afterwards, because the repair changes the
printer's config.

Selfcheck is handed in rather than imported: it reads this package's own markers, so importing it
here would make the two packages import each other.
"""
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..results import item, phase
from .errors import NeedsFullRecoverError
from .print_guard import guard_no_print
from .repair import repair_printer_setup

Selfcheck = Callable[[dict[str, str]], dict[str, Any]]

# The plugin_id the repair reports under: it is not a plugin, it is the printer's own setup. The
# app localizes this id in its results report.
PRINTER_SETUP_ID = "(printer setup)"

# Every selfcheck problem `repair_printer_setup` clears on its own. A failed re-apply marker is left
# out on purpose: clearing it only means something when the plugin is re-applied after.
SETUP_ONLY_PROBLEMS = frozenset({
    "includes_missing",
    "includes_present_while_off",
    "directory_missing",
    "plugin_half_removed",
})


def needs_only_setup_repair(report: dict[str, Any]) -> bool:
    """True when selfcheck found problems, all of them setup only, and no plugin's links drifted."""
    problems = report["problems"]
    if not problems or report["drift"]:
        return False
    return all(problem["kind"] in SETUP_ONLY_PROBLEMS for problem in problems)


def _problem_key(problem: dict[str, Any]) -> tuple[str, str]:
    """Kind and detail: two missing include lines share a kind and differ only by config name."""
    return problem["kind"], problem["detail"]


def _setup_result(found: list[dict[str, Any]], left: list[dict[str, Any]]) -> dict[str, Any]:
    """One row naming each problem found, ok only for the ones selfcheck no longer reports."""
    left_keys = {_problem_key(problem) for problem in left}
    items = [item(problem["detail"], ok=_problem_key(problem) not in left_keys)
             for problem in found]
    repair_phase = phase("setup", "Repair printer setup", items)
    reason = "" if repair_phase["ok"] else "selfcheck still reports a problem after the repair"
    return {"plugin_id": PRINTER_SETUP_ID, "ok": repair_phase["ok"], "skipped": False,
            "reason": reason, "log": [repair_phase]}


def run_setup_repair(data_root: Path, plugin_root: Path, vars: dict[str, str],
                     selfcheck: Selfcheck) -> list[dict[str, Any]]:
    """Repair the setup-only fault selfcheck reports, then ask selfcheck again to report the
    outcome. Refuses with NeedsFullRecoverError when the fault is not setup only."""
    guard_no_print()
    before = selfcheck(vars)
    if not needs_only_setup_repair(before):
        raise NeedsFullRecoverError("selfcheck reports more than a setup fault, or nothing")
    repair_printer_setup(data_root, plugin_root, vars)
    after = selfcheck(vars)
    return [_setup_result(before["problems"], after["problems"])]
