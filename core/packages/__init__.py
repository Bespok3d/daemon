"""
Package operations: install, uninstall.

A .b3 package is a zip containing manifest.json plus the plugin file tree.
Install is manifest-driven: dirs, symlinks, and unified-diff patches.
Signature verification is deferred until packages are signed.
"""

import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..intent import (
    RESTART_HOOKS,
    is_service_action,
    normalize_install,
)
from ..results import item as _item
from ..results import phase as _phase
from ..safety import OperationContext, OperationKind
from ..shell import run_one_command as _run_one_start_command
from ..shell import start_env as _start_env
from .archive import fix_ownership, read_manifest, unpack_package
from .deactivation import (
    DEACTIVATED_MARKER,
    RECOVERY_FAILURE_MARKER,
    clear_failure_markers,
    deactivate_plugin,
    neutralize_plugin,
    run_stop_commands,
)
from .dependencies import (
    installed_conflicts,
    installed_dependents,
    provided_services,
    required_services,
    topo_sort,
)
from .errors import ConflictError, DependentsError
from .manifest import manifest_at  # noqa: F401  re-export for api.routes
from .patches import apply_patches, restore_original_files
from .placement import (
    apply_modes,
    create_dirs,
    create_symlinks,
    remove_plugin_symlinks,
)
from .print_guard import (
    guard_batch_no_print,
    guard_no_print,
    guard_no_print_during_restart,
    guard_no_print_for_removal,
)
from .python_deps import (
    provision_deps_phases,
    remove_plugin_site_links,
    remove_plugin_venv,
)
from .recovery import op_context, restart_phases, restart_services
from .services import generate_service_scripts
from .templates import render_templates
from .user_vars import (
    USER_VARS_FILE,  # noqa: F401  re-export for tests
    expand,
    load_user_vars,
    missing_required_vars,
    persist_user_vars,
    validate_user_vars,  # noqa: F401  re-export for api.routes
    with_plugin_venv,
)

_DATA_ROOT = Path(os.environ.get("BESPOK3D_DATA_ROOT", "/userdata/bespok3d"))
PLUGIN_ROOT = _DATA_ROOT / "usr/local/plugins"

def _run_plugin_start_commands(cmds: list[str], vars: dict[str, str]) -> tuple[dict, list[str]]:
    """Run a plugin's plugin-specific start commands; defer Klipper/Moonraker restarts.

    Returns the start phase plus the deferred service-restart commands so the caller can
    run them once at the end of a batch instead of bouncing Klipper/Moonraker per plugin.
    """
    env = _start_env()
    expanded_cmds = [expand(cmd, vars) for cmd in cmds]
    immediate = [cmd for cmd in expanded_cmds if not is_service_action(cmd)]
    deferred = [cmd for cmd in expanded_cmds if is_service_action(cmd)]
    items = [_run_one_start_command(cmd, env) for cmd in immediate]
    return _phase("start", "Start commands", items), deferred


def ensure_lmd_control_script(jinni: Any, paths: dict[str, str]) -> None:
    """Place the jinni's hardened lmd control script at $BESPOK3D/etc/init.d/lmdctl (0755).

    Rendered into the persistent bespok3d tree (not symlinked into the redeployed daemon dir) so it
    survives a full daemon redeploy. Gated on the adapter advertising `lmd-control`, so a generic
    daemon and non-display adapters write nothing.
    """
    if "lmd-control" not in jinni.capability_flags():
        return
    target = Path(paths["BESPOK3D"]) / "etc/init.d/lmdctl"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(jinni.render_lmd_control_script(paths))
    target.chmod(0o755)


PhaseListener = Callable[[dict], None]


def _noop_phase(_phase: dict) -> None:
    return None


def _emit(phase: dict, notify: PhaseListener) -> dict:
    """Append-and-announce: report a phase the moment it finishes so a watcher (the install-progress
    feed) sees it live, while still returning it for the final install log."""
    notify(phase)
    return phase


def _install_apply_phases(plugin_dir: Path, manifest: dict, full_vars: dict[str, str], on_phase: PhaseListener | None = None) -> list[dict]:  # noqa: E501
    """Run a fresh install's phases, announcing each as it finishes. A core-service restart goes
    through the auto-fix safety net, so a plugin that breaks Klipper/Moonraker is deactivated and
    the printer stays usable (the protection recover/OTA already had)."""
    raw_inst = manifest.get("install", {})
    inst = normalize_install(raw_inst)
    notify = on_phase or _noop_phase
    phases = [
        _emit(apply_modes(plugin_dir, manifest.get("files", [])), notify),
        _emit(create_dirs(inst["dirs"], full_vars), notify),
        _emit(render_templates(inst["templates"], plugin_dir, full_vars), notify),
        _emit(generate_service_scripts(raw_inst.get("service", []), plugin_dir, full_vars), notify),  # noqa: E501
        _emit(create_symlinks(inst["symlinks"], plugin_dir, full_vars), notify),
        _emit(apply_patches(inst["patches"], plugin_dir, full_vars), notify),
        _emit(fix_ownership(plugin_dir, full_vars.get("RUNTIME_USER", "")), notify),
    ]
    phases.extend(_emit(phase, notify) for phase in provision_deps_phases(PLUGIN_ROOT, plugin_dir, full_vars))  # noqa: E501
    start_phase, deferred = _run_plugin_start_commands(inst["start"], full_vars)
    phases.append(_emit(start_phase, notify))
    phases.extend(_emit(phase, notify) for phase in restart_phases(PLUGIN_ROOT, deferred, full_vars, op_context(OperationKind.INSTALL, manifest)))  # noqa: E501
    return phases


def install(
    package_path: Path,
    vars: dict[str, str],
    user_vars: dict[str, str] | None = None,
    on_phase: PhaseListener | None = None,
) -> tuple[str, list[dict]]:
    manifest, plugin_dir, file_count = unpack_package(PLUGIN_ROOT, package_path)
    plugin_id: str = manifest["name"]

    conflicts = installed_conflicts(PLUGIN_ROOT, plugin_id, manifest)
    if conflicts:
        shutil.rmtree(plugin_dir, ignore_errors=True)
        raise ConflictError(plugin_id, conflicts)

    notify = on_phase or _noop_phase
    extract_items = [_item(f"Extracted {file_count} files", ok=True)]
    log: list[dict] = [_emit(_phase("extract", "Unpack", extract_items), notify)]

    persist_user_vars(plugin_dir, user_vars or {})
    full_vars = with_plugin_venv(vars, plugin_id)
    log.extend(_install_apply_phases(plugin_dir, manifest, full_vars, on_phase))
    if all(phase["ok"] for phase in log):
        clear_failure_markers(plugin_dir)

    return plugin_id, log


def reconfigure(
    plugin_id: str,
    vars: dict[str, str],
    user_vars: dict[str, str],
) -> tuple[str, list[dict]]:
    """Re-render a plugin's config templates from new values and restart its services.

    Lighter than a reinstall: files, symlinks, and patches are left untouched; only the
    rendered config files change. Relies on installs being idempotent.
    """
    plugin_dir = PLUGIN_ROOT / plugin_id
    manifest_path = plugin_dir / "manifest.json"
    if not manifest_path.exists():
        raise ValueError(f"plugin {plugin_id!r} is not installed")
    manifest = json.loads(manifest_path.read_text())
    guard_no_print_during_restart(manifest)

    full_vars = with_plugin_venv(vars, plugin_id)
    inst = normalize_install(manifest.get("install", {}))
    persist_user_vars(plugin_dir, user_vars)
    start_phase, deferred = _run_plugin_start_commands(inst.get("start", []), full_vars)
    phases = [
        render_templates(inst.get("templates", []), plugin_dir, full_vars),
        fix_ownership(plugin_dir, full_vars.get("RUNTIME_USER", "")),
        start_phase,
    ]
    phases.extend(restart_phases(PLUGIN_ROOT, deferred, full_vars, op_context(OperationKind.RECONFIGURE, manifest)))  # noqa: E501
    return plugin_id, phases


def _apply_plugin(plugin_dir: Path, raw_inst: dict, inst: dict, full_vars: dict[str, str]) -> tuple[list[dict], list[str]]:  # noqa: E501
    patches_orig = plugin_dir / "patches_orig"
    if patches_orig.exists():
        shutil.rmtree(patches_orig)
    phase_log: list[dict] = [
        render_templates(inst["templates"], plugin_dir, full_vars),
        generate_service_scripts(raw_inst.get("service", []), plugin_dir, full_vars),
        create_symlinks(inst["symlinks"], plugin_dir, full_vars),
        apply_patches(inst["patches"], plugin_dir, full_vars),
    ]
    phase_log.extend(provision_deps_phases(PLUGIN_ROOT, plugin_dir, full_vars))
    start_phase, deferred = _run_plugin_start_commands(inst["start"], full_vars)
    phase_log.append(start_phase)
    return phase_log, deferred


def _recover_one(
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
    if all(phase["ok"] for phase in phase_log):
        satisfied.update(provided_services(manifest))
        clear_failure_markers(plugin_dir)
        ok_result = {"plugin_id": plugin_id, "ok": True, "skipped": False, "reason": "", "log": phase_log}  # noqa: E501
        return ok_result, deferred

    reason = "install phase failed"
    (plugin_dir / RECOVERY_FAILURE_MARKER).write_text(json.dumps({"phases": phase_log}))
    deactivate_plugin(plugin_dir, vars, reason)
    failed = {"plugin_id": plugin_id, "ok": False, "skipped": False, "reason": reason, "log": phase_log}  # noqa: E501
    return failed, []


def recover(vars: dict[str, str]) -> list[dict]:
    """Re-apply all installed, non-deactivated plugins after OTA. Returns per-plugin results."""
    guard_no_print("recover plugins")
    if not PLUGIN_ROOT.exists():
        return []
    plugin_dirs = [
        plugin_dir for plugin_dir in PLUGIN_ROOT.iterdir()
        if plugin_dir.is_dir()
        and (plugin_dir / "manifest.json").exists()
        and not (plugin_dir / DEACTIVATED_MARKER).exists()
    ]
    if not plugin_dirs:
        return []
    ordered = topo_sort(plugin_dirs)
    manifests = {
        plugin_dir: json.loads((plugin_dir / "manifest.json").read_text())
        for plugin_dir in ordered
    }
    all_provided: set[str] = set()
    for manifest in manifests.values():
        all_provided.update(provided_services(manifest))
    satisfied: set[str] = set()
    results: list[dict] = []
    deferred_restarts: list[str] = []
    for plugin_dir in ordered:
        result, deferred = _recover_one(plugin_dir, manifests[plugin_dir], satisfied, all_provided, vars)  # noqa: E501
        results.append(result)
        if result["ok"]:
            deferred_restarts.extend(deferred)
    unique_restarts = list(dict.fromkeys(deferred_restarts))
    if unique_restarts:
        results.append(restart_services(PLUGIN_ROOT, unique_restarts, vars, OperationContext(OperationKind.RECOVER)))  # noqa: E501
    return results


def _apply_install_deferred(plugin_dir: Path, manifest: dict, vars: dict[str, str]) -> tuple[list[dict], list[str]]:  # noqa: E501
    """Run a fresh install's file phases, deferring service restarts to the batch end."""
    raw_inst = manifest.get("install", {})
    inst = normalize_install(raw_inst)
    log = [
        apply_modes(plugin_dir, manifest.get("files", [])),
        create_dirs(inst["dirs"], vars),
        render_templates(inst["templates"], plugin_dir, vars),
        generate_service_scripts(raw_inst.get("service", []), plugin_dir, vars),
        create_symlinks(inst["symlinks"], plugin_dir, vars),
        apply_patches(inst["patches"], plugin_dir, vars),
        fix_ownership(plugin_dir, vars.get("RUNTIME_USER", "")),
    ]
    log.extend(provision_deps_phases(PLUGIN_ROOT, plugin_dir, vars))
    start_phase, deferred = _run_plugin_start_commands(inst["start"], vars)
    log.append(start_phase)
    return log, deferred


def _update_one(base_vars: dict[str, str], package_path: Path, user_vars: dict[str, str]) -> tuple[dict, list[str]]:  # noqa: E501
    manifest, plugin_dir, file_count = unpack_package(PLUGIN_ROOT, package_path)
    plugin_id = manifest["name"]
    full_vars = with_plugin_venv({**base_vars, **user_vars}, plugin_id)
    persist_user_vars(plugin_dir, user_vars)
    extract = _phase("extract", "Unpack", [_item(f"Extracted {file_count} files", ok=True)])
    phases, deferred = _apply_install_deferred(plugin_dir, manifest, full_vars)
    log = [extract, *phases]
    ok = all(phase["ok"] for phase in log)
    if ok:
        clear_failure_markers(plugin_dir)
    reason = "" if ok else "update phase failed"
    result = {"plugin_id": plugin_id, "ok": ok, "skipped": False, "reason": reason, "log": log}
    return result, (deferred if ok else [])


def update_batch(
    base_vars: dict[str, str],
    package_paths: list[Path],
    vars_by_id: dict[str, dict[str, str]],
) -> list[dict]:
    """Update several plugins, restarting affected services only once at the end.

    Each package is unpacked and re-applied (templates, symlinks, patches, inline start commands);
    init-script and nginx restarts are deferred, deduped, and run once, then Klipper and Moonraker
    are awaited healthy. Mirrors recover's deferred-restart batching for the update path. Packages
    are applied in the order given, so callers pass dependencies before their dependents.
    """
    if not package_paths:
        return []
    specs = [(package_path, read_manifest(package_path)) for package_path in package_paths]
    guard_batch_no_print([manifest for _, manifest in specs])
    results: list[dict] = []
    deferred_restarts: list[str] = []
    for package_path, manifest in specs:
        user_vars = vars_by_id.get(manifest["name"], {})
        result, deferred = _update_one(base_vars, package_path, user_vars)
        results.append(result)
        deferred_restarts.extend(deferred)
    unique_restarts = list(dict.fromkeys(deferred_restarts))
    if unique_restarts:
        only = specs[0][1]["name"] if len(specs) == 1 else None
        ctx = OperationContext(OperationKind.UPDATE, plugin_id=only)
        results.append(restart_services(PLUGIN_ROOT, unique_restarts, base_vars, ctx))
    return results


def _uninstall_from_manifest(manifest_path: Path, plugin_dir: Path, vars: dict[str, str]) -> None:
    manifest = json.loads(manifest_path.read_text())
    install_spec = normalize_install(manifest.get("install", {}))
    full_vars = {**vars, **load_user_vars(plugin_dir)}
    run_stop_commands(install_spec["stops"] + manifest.get("stop", []), full_vars)
    remove_plugin_symlinks(install_spec["symlinks"], plugin_dir, full_vars)
    restore_original_files(install_spec["patches"], plugin_dir / "patches_orig", full_vars)


def _remove_one(plugin_dir: Path, vars: dict[str, str]) -> None:
    manifest_path = plugin_dir / "manifest.json"
    if manifest_path.exists():
        _uninstall_from_manifest(manifest_path, plugin_dir, vars)
    remove_plugin_site_links(plugin_dir, vars)
    remove_plugin_venv(plugin_dir.name, vars)
    shutil.rmtree(plugin_dir)


def _remove_with_dependents(plugin_id: str, vars: dict[str, str], removed: list[str]) -> None:
    for dependent in installed_dependents(PLUGIN_ROOT, plugin_id):
        if dependent not in removed:
            _remove_with_dependents(dependent, vars, removed)
    plugin_dir = PLUGIN_ROOT / plugin_id
    if plugin_dir.exists() and plugin_id not in removed:
        _remove_one(plugin_dir, vars)
        removed.append(plugin_id)


def _removal_restart_commands(plugin_ids: list[str], vars: dict[str, str]) -> list[str]:
    """Core-service restart hooks declared by the plugins being removed, expanded and deduped.

    Install runs a plugin's `restart` hooks so its config/extra takes effect; uninstall must run the
    same hooks so the REMOVAL takes effect (Klipper keeps a now-deleted [section] loaded, and nginx
    keeps a removed web location, until the service restarts).
    """
    commands: list[str] = []
    for plugin_id in plugin_ids:
        manifest_path = PLUGIN_ROOT / plugin_id / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text())
        for hook in manifest.get("install", {}).get("restart", []):
            command = RESTART_HOOKS.get(hook)
            if command:
                commands.append(expand(command, vars))
    return list(dict.fromkeys(commands))


def uninstall(plugin_id: str, vars: dict[str, str], cascade: bool = False) -> list[str]:
    """Remove a plugin. Refuses if installed dependents need it, unless cascade removes them too.

    Returns the ids removed, dependents first, target last.
    """
    plugin_dir = PLUGIN_ROOT / plugin_id
    if not plugin_dir.exists():
        raise FileNotFoundError(plugin_id)
    dependents = installed_dependents(PLUGIN_ROOT, plugin_id)
    if dependents and not cascade:
        raise DependentsError(plugin_id, dependents)
    guard_no_print_for_removal(PLUGIN_ROOT, [plugin_id, *dependents])
    restart_commands = _removal_restart_commands([*dependents, plugin_id], vars)
    removed: list[str] = []
    _remove_with_dependents(plugin_id, vars, removed)
    if restart_commands:
        restart_services(PLUGIN_ROOT, restart_commands, vars, OperationContext(OperationKind.UNINSTALL, plugin_id))  # noqa: E501
    return removed


_GLOBAL_DEACTIVATED_MARKER = "etc/deactivated"


def _remove_include_line(cfg_path: Path, pattern: str) -> None:
    if not cfg_path.exists():
        return
    text = cfg_path.read_text()
    cfg_path.write_text(
        "".join(line for line in text.splitlines(keepends=True) if pattern not in line)
    )


def _deactivate_plugin_dir(plugin_dir: Path, vars: dict[str, str]) -> None:
    if not plugin_dir.is_dir() or not (plugin_dir / "manifest.json").exists():
        return
    neutralize_plugin(plugin_dir, vars)


def _deactivate_plugins_in(plugin_root: Path, vars: dict[str, str]) -> None:
    if not plugin_root.exists():
        return
    for plugin_dir in plugin_root.iterdir():
        _deactivate_plugin_dir(plugin_dir, vars)


def _write_deactivated_marker(data_root: Path) -> None:
    marker = data_root / _GLOBAL_DEACTIVATED_MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()


def deactivate_all(vars: dict[str, str]) -> None:
    """Stop all plugins and remove config hooks; leave plugin files intact."""
    guard_no_print("deactivate plugins")
    data_root = Path(vars["BESPOK3D"])
    _deactivate_plugins_in(data_root / "usr/local/plugins", vars)
    _remove_include_line(Path(vars["PRINTER_CFG"]), "[include bespok3d/klipper")
    _remove_include_line(Path(vars["MOONRAKER_CFG"]), "[include bespok3d/moonraker")
    _write_deactivated_marker(data_root)


def _uninstall_plugins_in(plugin_root: Path, vars: dict[str, str]) -> None:
    if not plugin_root.exists():
        return
    plugin_ids = [plugin_dir.name for plugin_dir in plugin_root.iterdir() if plugin_dir.is_dir()]
    for plugin_id in plugin_ids:
        try:
            uninstall(plugin_id, vars)
        except Exception:  # noqa: BLE001
            pass


def _prune_links_and_empty_dirs(root: Path) -> None:
    """Remove our symlinks and any directories left empty, but keep real files.

    The `config/bespok3d` directory is intentionally preserved: a user may have dropped
    their own .cfg files in it. We only take back what Bespok3d put there (symlinks).
    """
    if not root.is_dir():
        return
    for child in sorted(root.iterdir()):
        if child.is_symlink():
            child.unlink()
        elif child.is_dir():
            _prune_links_and_empty_dirs(child)
    if not any(root.iterdir()):
        root.rmdir()


def _remove_bespok3d_config_dir(vars: dict[str, str]) -> None:
    config_dir = Path(vars.get("BESPOK3D_KLIPPER", "")).parent
    if config_dir.name == "bespok3d":
        _prune_links_and_empty_dirs(config_dir)


def teardown(vars: dict[str, str]) -> None:
    """Uninstall all plugins and remove config hooks; SSH caller removes the workspace."""
    # Guard at the top: the per-plugin uninstall guard is swallowed by _uninstall_plugins_in.
    guard_no_print("remove all plugins")
    data_root = Path(vars["BESPOK3D"])
    _uninstall_plugins_in(data_root / "usr/local/plugins", vars)
    _remove_include_line(Path(vars["PRINTER_CFG"]), "[include bespok3d/klipper")
    _remove_include_line(Path(vars["MOONRAKER_CFG"]), "[include bespok3d/moonraker")
    _remove_bespok3d_config_dir(vars)
