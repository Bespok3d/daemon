"""Taking a plugin out of effect and recording it: run its stop commands, undo what install placed
on the system (symlinks, patched files, linked libs, venv), and write/clear the deactivated and
recovery-failure markers. Shared by the recovery safety net and the uninstall/teardown paths.
"""

import json
from pathlib import Path

from .. import jinni_client
from ..intent import normalize_install
from ..safety import OperationContext, OperationKind, diagnose_module_failure
from .manifest import manifest_at
from .patches import restore_original_files
from .placement import remove_plugin_symlinks
from .plugin_venv import remove_plugin_venv
from .python_deps import remove_plugin_site_links
from .user_vars import expand, load_user_vars

DEACTIVATED_MARKER = "deactivated.json"
RECOVERY_FAILURE_MARKER = "recovery_failure.json"
_KMODULE_LOAD_PHASE = "kmodule-load"


def _kmodule_load_diagnosis(phase_log: list[dict]) -> str:
    """The jinni token a failed kernel-module load tagged onto its phase, or "" if none failed."""
    for logged_phase in phase_log:
        if logged_phase.get("id") == _KMODULE_LOAD_PHASE and not logged_phase["ok"]:
            return str(logged_phase.get("diagnosis", ""))
    return ""


def load_failure_reason(
    phase_log: list[dict], kind: OperationKind, plugin_id: str, fallback: str
) -> str:
    """The deactivation reason for a failed install/recover phase run: the jinni's kernel-module
    token when a module load failed with a known cause (so the app localizes e.g. a vermagic
    mismatch after an OTA kernel bump), else the generic fallback."""
    ctx = OperationContext(kind=kind, plugin_id=plugin_id)
    decision = diagnose_module_failure(_kmodule_load_diagnosis(phase_log), ctx)
    return decision.signal if decision else fallback


def run_stop_commands(cmds: list[str], vars: dict[str, str]) -> None:
    """Run a plugin's stop commands best-effort; the jinni executes them (ADR-0037), the daemon only
    resolves and forwards. The outcome is ignored: a stop that fails (service already down) must not
    block taking the plugin off the system."""
    expanded = [expand(cmd, vars) for cmd in cmds]
    if expanded:
        jinni_client.run_actions(expanded)


def clear_failure_markers(plugin_dir: Path) -> None:
    """A plugin that re-applies cleanly is no longer failed or deactivated; drop stale markers."""
    (plugin_dir / DEACTIVATED_MARKER).unlink(missing_ok=True)
    (plugin_dir / RECOVERY_FAILURE_MARKER).unlink(missing_ok=True)


def neutralize_plugin(plugin_dir: Path, vars: dict[str, str]) -> None:
    """Stop a plugin affecting the system: drop its symlinks, restore patched files, remove its
    linked libs and venv. Files in the plugin dir stay, so recover/reactivate can rebuild it."""
    manifest = manifest_at(plugin_dir)
    full_vars = {**vars, **load_user_vars(plugin_dir)}
    ops = normalize_install(manifest.get("install", {}), jinni_client.variant_facts())
    run_stop_commands(ops["stops"] + manifest.get("stop", []), full_vars)
    remove_plugin_symlinks(ops["symlinks"], plugin_dir, full_vars)
    restore_original_files(ops["patches"], plugin_dir / "patches_orig", full_vars)
    remove_plugin_site_links(plugin_dir, full_vars)
    remove_plugin_venv(plugin_dir.name, full_vars)


def deactivate_plugin(plugin_dir: Path, vars: dict[str, str], reason: str) -> None:
    if (plugin_dir / "manifest.json").exists():
        neutralize_plugin(plugin_dir, vars)
    (plugin_dir / DEACTIVATED_MARKER).write_text(json.dumps({"reason": reason}))


def finalize_install_outcome(plugin_dir: Path, vars: dict[str, str], log: list[dict]) -> None:
    """Settle a finished install by its phase log: clear stale markers on a clean run; on a failed
    required phase, take the half-applied plugin off the system (drop its symlinks, restore any
    patched source) and mark it deactivated, the protection recover gives a broken plugin. The
    install log is retained: every phase is still returned to the app and the plugin dir stays on
    disk for inspection. The marker check leaves a plugin the restart safety net already deactivated
    untouched, so its diagnosis reason is not overwritten."""
    if all(logged_phase["ok"] for logged_phase in log):
        clear_failure_markers(plugin_dir)
        return
    if (plugin_dir / DEACTIVATED_MARKER).exists():
        return
    reason = load_failure_reason(log, OperationKind.INSTALL, plugin_dir.name,
                                 "install failed: a required phase did not apply")
    deactivate_plugin(plugin_dir, vars, reason)
