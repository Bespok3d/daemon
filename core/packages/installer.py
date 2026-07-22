"""A fresh single-plugin install: unpack a .b3, refuse it up front if it conflicts with or lacks a
required service, then apply its install (modes, dirs, templates, service scripts, symlinks,
patches, ownership, baked deps, start commands) through the shared phase runner
(`apply_install_deferred`, also used by the batched update in `updater.py`) and restart core
services live through the safety net. The config-only reconfigure is its sibling in
`reconfigurer.py`.

The orchestrator (`core/packages/__init__.py`) owns the plugin root and passes it in, so this
worker stays independent of where plugins live on disk.
"""

from collections.abc import Callable
from pathlib import Path
from typing import NoReturn

from .. import jinni_client
from ..intent import normalize_install
from ..results import item, phase
from ..safety import OperationKind
from .archive import discard_extraction, fix_ownership, unpack_package
from .deactivation import finalize_install_outcome
from .dependencies import installed_conflicts, unsatisfied_requirements
from .errors import ConflictError, RequirementError
from .integrity import CHECKSUM_MISMATCH, IntegrityError, verify_files
from .kmodules import generate_module_loaders, load_modules
from .members import installed_files
from .patches import apply_patches
from .placement import apply_modes, create_dirs, create_symlinks
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
    inst = normalize_install(raw_inst, jinni_client.variant_facts())
    mismatched = verify_files(plugin_dir, installed_files(manifest.get("files", [])))
    if mismatched:
        raise IntegrityError(manifest["name"], CHECKSUM_MISMATCH, mismatched)
    phases = [
        _emit(apply_modes(plugin_dir, manifest.get("files", [])), notify),
        _emit(create_dirs(inst["dirs"], vars), notify),
        _emit(render_templates(inst["templates"], plugin_dir, vars), notify),
        _emit(generate_service_scripts(raw_inst.get("service", []), plugin_dir, vars), notify),
        _emit(generate_module_loaders(raw_inst.get("kmodule", []), plugin_dir, vars), notify),
        _emit(create_symlinks(inst["symlinks"], plugin_dir, vars), notify),
        _emit(apply_patches(inst["patches"], plugin_dir, vars), notify),
        _emit(fix_ownership(plugin_dir, vars.get("RUNTIME_USER", "")), notify),
        _emit(load_modules(inst["module_loads"], inst["module_load_names"], vars), notify),
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


def _refuse(plugin_dir: Path, refusal: Exception) -> NoReturn:
    """A refused install takes its own extraction with it."""
    discard_extraction(plugin_dir)
    raise refusal


def _refuse_unmet_dependencies(
    plugin_root: Path,
    plugin_dir: Path,
    plugin_id: str,
    manifest: dict,
) -> None:
    """Up-front refusals, before a single file is placed: a plugin that collides with an installed
    one, or one whose required service is absent."""
    conflicts = installed_conflicts(plugin_root, plugin_id, manifest)
    if conflicts:
        _refuse(plugin_dir, ConflictError(plugin_id, conflicts))

    missing = unsatisfied_requirements(plugin_root, plugin_id, manifest)
    if missing:
        _refuse(plugin_dir, RequirementError(plugin_id, missing))


def run_install(
    plugin_root: Path,
    package_path: Path,
    vars: dict[str, str],
    user_vars: dict[str, str] | None = None,
    on_phase: PhaseListener | None = None,
) -> tuple[str, list[dict]]:
    manifest, plugin_dir, file_count = unpack_package(plugin_root, package_path)
    plugin_id: str = manifest["name"]
    _refuse_unmet_dependencies(plugin_root, plugin_dir, plugin_id, manifest)

    notify = on_phase or _noop_phase
    extract_items = [item(f"Extracted {file_count} files", ok=True)]
    log: list[dict] = [_emit(phase("extract", "Unpack", extract_items), notify)]

    persist_user_vars(plugin_dir, user_vars or {})
    full_vars = with_plugin_venv(vars, plugin_id)
    try:
        log.extend(_install_apply_phases(plugin_root, plugin_dir, manifest, full_vars, notify))
    except IntegrityError as tampered_package:
        _refuse(plugin_dir, tampered_package)
    finalize_install_outcome(plugin_dir, full_vars, log)
    return plugin_id, log
