"""OTA per-plugin re-apply: rebuild one installed plugin's effect on the system after an OTA wipe.

`recover_one` is the unit the orchestrator's `recover()` runs per plugin in dependency order: skip
if a dependency is unsatisfied or a required variable is missing, else re-apply the install
(templates, service scripts, symlinks, patches, baked deps, start commands) deferring core-service
restarts. A plugin whose re-apply fails is deactivated and its failure recorded, so the printer
stays usable.
"""

import json
import shutil
from pathlib import Path

from ...intent import normalize_install
from ..deactivation import RECOVERY_FAILURE_MARKER, clear_failure_markers, deactivate_plugin
from ..dependencies import provided_services, required_services
from ..patches import apply_patches
from ..placement import create_symlinks
from ..python_deps import provision_deps_phases
from ..services import generate_service_scripts
from ..start_commands import run_plugin_start_commands
from ..templates import render_templates
from ..user_vars import load_user_vars, missing_required_vars, with_plugin_venv


def _apply_plugin(plugin_dir: Path, raw_inst: dict, inst: dict,
                  full_vars: dict[str, str]) -> tuple[list[dict], list[str]]:
    patches_orig = plugin_dir / "patches_orig"
    if patches_orig.exists():
        shutil.rmtree(patches_orig)
    phase_log: list[dict] = [
        render_templates(inst["templates"], plugin_dir, full_vars),
        generate_service_scripts(raw_inst.get("service", []), plugin_dir, full_vars),
        create_symlinks(inst["symlinks"], plugin_dir, full_vars),
        apply_patches(inst["patches"], plugin_dir, full_vars),
    ]
    phase_log.extend(provision_deps_phases(plugin_dir.parent, plugin_dir, full_vars))
    start_phase, deferred = run_plugin_start_commands(inst["start"], full_vars)
    phase_log.append(start_phase)
    return phase_log, deferred


def recover_one(
    plugin_dir: Path,
    manifest: dict,
    satisfied: set[str],
    all_provided: set[str],
    vars: dict[str, str],
) -> tuple[dict, list[str]]:
    plugin_id = plugin_dir.name
    missing_deps = [
        service for service in required_services(manifest)
        if service in all_provided and service not in satisfied
    ]
    if missing_deps:
        reason = f"dependency not satisfied: {', '.join(missing_deps)}"
        return {"plugin_id": plugin_id, "ok": False, "skipped": True, "reason": reason, "log": []}, []  # noqa: E501

    full_vars = with_plugin_venv({**vars, **load_user_vars(plugin_dir)}, plugin_id)
    missing_vars = missing_required_vars(manifest, full_vars)
    if missing_vars:
        reason = f"missing required variable(s): {', '.join(missing_vars)}; reinstall the plugin"
        return {"plugin_id": plugin_id, "ok": False, "skipped": False, "reason": reason, "log": []}, []  # noqa: E501

    raw_inst = manifest.get("install", {})
    inst = normalize_install(raw_inst)
    phase_log, deferred = _apply_plugin(plugin_dir, raw_inst, inst, full_vars)
    if not all(phase["ok"] for phase in phase_log):
        reason = "install phase failed"
        (plugin_dir / RECOVERY_FAILURE_MARKER).write_text(json.dumps({"phases": phase_log}))
        deactivate_plugin(plugin_dir, vars, reason)
        failed = {"plugin_id": plugin_id, "ok": False, "skipped": False, "reason": reason, "log": phase_log}  # noqa: E501
        return failed, []

    satisfied.update(provided_services(manifest))
    clear_failure_markers(plugin_dir)
    recovered = {"plugin_id": plugin_id, "ok": True, "skipped": False, "reason": "", "log": phase_log}  # noqa: E501
    return recovered, deferred
