"""Install-shaped package operations: a fresh install and a config-only reconfigure.

Both apply a plugin's install (modes, dirs, templates, service scripts, symlinks, patches,
ownership, baked deps, start commands) through ONE shared phase runner (`apply_install_deferred`,
also used by the batched update in `updater.py`). They differ only in how the core-service restart
runs: install runs it immediately through the safety net and streams each phase live to a notify
callback; reconfigure re-renders config and restarts.

The orchestrator (`core/packages/__init__.py`) owns the plugin root and passes it in, so these
workers stay independent of where plugins live on disk.
"""

import shutil
from collections.abc import Callable
from pathlib import Path

from ..intent import normalize_install
from ..results import item, phase
from ..safety import OperationKind
from .archive import fix_ownership, unpack_package
from .deactivation import finalize_install_outcome
from .dependencies import installed_conflicts
from .errors import ConflictError
from .manifest import manifest_at
from .patches import apply_patches
from .placement import apply_modes, create_dirs, create_symlinks
from .print_guard import guard_no_print_during_restart
from .python_deps import provision_deps_phases
from .recovery import op_context, restart_phases
from .services import generate_service_scripts
from .start_commands import run_plugin_start_commands
from .templates import render_templates
from .user_vars import persist_user_vars, with_plugin_venv

PhaseListener = Callable[[dict], None]


def _noop_phase(_phase: dict) -> None:
    return None


def _emit(finished_phase: dict, notify: PhaseListener) -> dict:
    """Append-and-announce: report a phase the moment it finishes so a watcher (the install-progress
    feed) sees it live, while still returning it for the final install log."""
    notify(finished_phase)
    return finished_phase


def apply_install_deferred(
    plugin_root: Path,
    plugin_dir: Path,
    manifest: dict,
    vars: dict[str, str],
    notify: PhaseListener = _noop_phase,
) -> tuple[list[dict], list[str]]:
    """Run a fresh install's file phases, announcing each as it finishes, and DEFER the core-service
    restart by returning its commands for the caller to run. Shared by install (live, restart now)
    and update_batch (silent, restart batched)."""
    raw_inst = manifest.get("install", {})
    inst = normalize_install(raw_inst)
    phases = [
        _emit(apply_modes(plugin_dir, manifest.get("files", [])), notify),
        _emit(create_dirs(inst["dirs"], vars), notify),
        _emit(render_templates(inst["templates"], plugin_dir, vars), notify),
        _emit(generate_service_scripts(raw_inst.get("service", []), plugin_dir, vars), notify),
        _emit(create_symlinks(inst["symlinks"], plugin_dir, vars), notify),
        _emit(apply_patches(inst["patches"], plugin_dir, vars), notify),
        _emit(fix_ownership(plugin_dir, vars.get("RUNTIME_USER", "")), notify),
    ]
    phases.extend(_emit(dep_phase, notify) for dep_phase in provision_deps_phases(plugin_root, plugin_dir, vars))  # noqa: E501
    start_phase, deferred = run_plugin_start_commands(inst["start"], vars)
    phases.append(_emit(start_phase, notify))
    return phases, deferred


def _install_apply_phases(
    plugin_root: Path,
    plugin_dir: Path,
    manifest: dict,
    full_vars: dict[str, str],
    notify: PhaseListener,
) -> list[dict]:
    """Install's full phase run: apply the install live, then restart core services immediately
    through the safety net (a plugin that breaks Klipper/Moonraker is deactivated so the printer
    stays usable, the protection recover/OTA already had), announcing each restart phase live."""
    phases, deferred = apply_install_deferred(plugin_root, plugin_dir, manifest, full_vars, notify)
    ctx = op_context(OperationKind.INSTALL, manifest)
    phases.extend(_emit(restart_phase, notify) for restart_phase in restart_phases(plugin_root, deferred, full_vars, ctx))  # noqa: E501
    return phases


def run_install(
    plugin_root: Path,
    package_path: Path,
    vars: dict[str, str],
    user_vars: dict[str, str] | None = None,
    on_phase: PhaseListener | None = None,
) -> tuple[str, list[dict]]:
    manifest, plugin_dir, file_count = unpack_package(plugin_root, package_path)
    plugin_id: str = manifest["name"]

    conflicts = installed_conflicts(plugin_root, plugin_id, manifest)
    if conflicts:
        shutil.rmtree(plugin_dir, ignore_errors=True)
        raise ConflictError(plugin_id, conflicts)

    notify = on_phase or _noop_phase
    extract_items = [item(f"Extracted {file_count} files", ok=True)]
    log: list[dict] = [_emit(phase("extract", "Unpack", extract_items), notify)]

    persist_user_vars(plugin_dir, user_vars or {})
    full_vars = with_plugin_venv(vars, plugin_id)
    log.extend(_install_apply_phases(plugin_root, plugin_dir, manifest, full_vars, notify))
    finalize_install_outcome(plugin_dir, full_vars, log)
    return plugin_id, log


def run_reconfigure(
    plugin_root: Path,
    plugin_id: str,
    vars: dict[str, str],
    user_vars: dict[str, str],
) -> tuple[str, list[dict]]:
    """Re-render a plugin's config templates from new values and restart its services.

    Lighter than a reinstall: files, symlinks, and patches are left untouched; only the
    rendered config files change. Relies on installs being idempotent.
    """
    plugin_dir = plugin_root / plugin_id
    if not (plugin_dir / "manifest.json").exists():
        raise ValueError(f"plugin {plugin_id!r} is not installed")
    manifest = manifest_at(plugin_dir)
    guard_no_print_during_restart(manifest)

    full_vars = with_plugin_venv(vars, plugin_id)
    inst = normalize_install(manifest.get("install", {}))
    persist_user_vars(plugin_dir, user_vars)
    start_phase, deferred = run_plugin_start_commands(inst.get("start", []), full_vars)
    ctx = op_context(OperationKind.RECONFIGURE, manifest)
    phases = [
        render_templates(inst.get("templates", []), plugin_dir, full_vars),
        fix_ownership(plugin_dir, full_vars.get("RUNTIME_USER", "")),
        start_phase,
    ]
    phases.extend(restart_phases(plugin_root, deferred, full_vars, ctx))
    return plugin_id, phases
