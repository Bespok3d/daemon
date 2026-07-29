# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""OTA per-plugin re-apply: rebuild one installed plugin's effect on the system after an OTA wipe.

`recover_one` is the unit the orchestrator's `recover()` runs per plugin in dependency order: skip
if a dependency is unsatisfied or a required variable is missing, else re-apply the install through
the shared install spine (`installer.apply_install_deferred`, the same pipeline a fresh install and
a batched update run) so recovery cannot drift from install, deferring core-service restarts. A
plugin whose re-apply fails is deactivated and its failure recorded, so the printer stays usable.
"""

import json
import shutil
from pathlib import Path

from ...safety import OperationKind
from ..deactivation import (
    RECOVERY_FAILURE_MARKER,
    clear_failure_markers,
    deactivate_plugin,
    load_failure_reason,
)
from ..dependencies import provided_services, required_services
from ..user_vars import load_user_vars, missing_required_vars, with_plugin_venv


def _apply_plugin(plugin_dir: Path, manifest: dict,
                  full_vars: dict[str, str]) -> tuple[list[dict], list[str]]:
    # Function-local: installer imports the recovery package at module load, so importing
    # apply_install_deferred at module top would hit a partially-initialized installer and raise.
    from ..installer import apply_install_deferred

    patches_orig = plugin_dir / "patches_orig"
    if patches_orig.exists():
        shutil.rmtree(patches_orig)
    return apply_install_deferred(plugin_dir.parent, plugin_dir, manifest, full_vars)


def recover_one(
    plugin_dir: Path,
    manifest: dict,
    satisfied: set[str],
    all_provided: set[str],
    vars: dict[str, str],
) -> tuple[dict, list[str]]:
    plugin_id = plugin_dir.name
    full_vars = with_plugin_venv({**vars, **load_user_vars(plugin_dir)}, plugin_id)
    precondition = _precondition_skip(plugin_id, manifest, full_vars, satisfied, all_provided)
    if precondition is not None:
        return precondition

    try:
        phase_log, deferred = _apply_plugin(plugin_dir, manifest, full_vars)
    except Exception as exc:  # noqa: BLE001 - one plugin's recover error must NOT abort the rest
        # printer-never-broken: deactivate just this plugin and report the real error in its result,
        # so recover completes for the others and the app shows what failed (not a bare 500).
        return _record_failure(plugin_dir, vars, f"recover error: {type(exc).__name__}: {exc}",
                               {"error": str(exc)}, []), []
    if not all(phase["ok"] for phase in phase_log):
        reason = load_failure_reason(phase_log, OperationKind.RECOVER, plugin_id, "install phase failed")  # noqa: E501
        return _record_failure(plugin_dir, vars, reason, {"phases": phase_log}, phase_log), []

    satisfied.update(provided_services(manifest))
    clear_failure_markers(plugin_dir)
    recovered = {"plugin_id": plugin_id, "ok": True, "skipped": False, "reason": "", "log": phase_log}  # noqa: E501
    return recovered, deferred


def _precondition_skip(
    plugin_id: str, manifest: dict, full_vars: dict[str, str],
    satisfied: set[str], all_provided: set[str],
) -> tuple[dict, list[str]] | None:
    """A skip (a dependency another recovered plugin should provide is not satisfied) or a fail (a
    required variable is missing), or None to proceed with the re-apply."""
    missing_deps = [service for service in required_services(manifest)
                    if service in all_provided and service not in satisfied]
    if missing_deps:
        reason = f"dependency not satisfied: {', '.join(missing_deps)}"
        return {"plugin_id": plugin_id, "ok": False, "skipped": True, "reason": reason, "log": []}, []  # noqa: E501
    missing_vars = missing_required_vars(manifest, full_vars)
    if missing_vars:
        reason = f"missing required variable(s): {', '.join(missing_vars)}; reinstall the plugin"
        return {"plugin_id": plugin_id, "ok": False, "skipped": False, "reason": reason, "log": []}, []  # noqa: E501
    return None


def _record_failure(plugin_dir: Path, vars: dict[str, str], reason: str,
                    marker: dict, log: list[dict]) -> dict:
    """Mark a plugin's recover failed and deactivate it (so it is off the system but its files stay
    for a fixed version to revive), returning the failed result the orchestrator reports."""
    (plugin_dir / RECOVERY_FAILURE_MARKER).write_text(json.dumps(marker))
    deactivate_plugin(plugin_dir, vars, reason)
    return {"plugin_id": plugin_dir.name, "ok": False, "skipped": False, "reason": reason, "log": log}  # noqa: E501
