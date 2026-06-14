"""Package-operations facade.

Re-exports the public package API the routes import and owns the plugin root, injecting it into the
worker modules. The install-shaped operations (install, reconfigure, update-batch) live in
`installer.py`; recover, uninstall, and the deactivate/teardown lifecycle still live here pending
their own extraction.

A .b3 package is a zip of manifest.json plus the plugin file tree. Signature verification is
deferred until packages are signed.
"""

import json
import os
import shutil
from pathlib import Path
from typing import Any

from ..intent import RESTART_HOOKS, normalize_install
from ..safety import OperationContext, OperationKind
from .deactivation import DEACTIVATED_MARKER, neutralize_plugin, run_stop_commands
from .dependencies import installed_dependents, provided_services, topo_sort
from .errors import (
    ConflictError,  # noqa: F401  re-export for api.routes
    DependentsError,
)
from .installer import (
    PhaseListener,  # noqa: F401  re-export for api.routes
    run_install,
    run_reconfigure,
    run_update_batch,
)
from .manifest import manifest_at
from .patches import restore_original_files
from .placement import remove_plugin_symlinks
from .print_guard import guard_no_print, guard_no_print_for_removal
from .python_deps import remove_plugin_site_links, remove_plugin_venv
from .recovery import recover_one, restart_services
from .user_vars import (
    USER_VARS_FILE,  # noqa: F401  re-export for tests
    expand,
    load_user_vars,
    validate_user_vars,  # noqa: F401  re-export for api.routes
)

_DATA_ROOT = Path(os.environ.get("BESPOK3D_DATA_ROOT", "/userdata/bespok3d"))
PLUGIN_ROOT = _DATA_ROOT / "usr/local/plugins"

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


def install(
    package_path: Path,
    vars: dict[str, str],
    user_vars: dict[str, str] | None = None,
    on_phase: PhaseListener | None = None,
) -> tuple[str, list[dict]]:
    return run_install(PLUGIN_ROOT, package_path, vars, user_vars, on_phase)


def reconfigure(plugin_id: str, vars: dict[str, str], user_vars: dict[str, str]) -> tuple[str, list[dict]]:  # noqa: E501
    return run_reconfigure(PLUGIN_ROOT, plugin_id, vars, user_vars)


def update_batch(
    base_vars: dict[str, str],
    package_paths: list[Path],
    vars_by_id: dict[str, dict[str, str]],
) -> list[dict]:
    return run_update_batch(PLUGIN_ROOT, base_vars, package_paths, vars_by_id)


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
    manifests = {plugin_dir: manifest_at(plugin_dir) for plugin_dir in ordered}
    all_provided: set[str] = set()
    for manifest in manifests.values():
        all_provided.update(provided_services(manifest))
    satisfied: set[str] = set()
    results: list[dict] = []
    deferred_restarts: list[str] = []
    for plugin_dir in ordered:
        result, deferred = recover_one(plugin_dir, manifests[plugin_dir], satisfied, all_provided, vars)  # noqa: E501
        results.append(result)
        if result["ok"]:
            deferred_restarts.extend(deferred)
    unique_restarts = list(dict.fromkeys(deferred_restarts))
    if unique_restarts:
        results.append(restart_services(PLUGIN_ROOT, unique_restarts, vars, OperationContext(OperationKind.RECOVER)))  # noqa: E501
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
