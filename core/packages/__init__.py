"""Package-operations facade.

Re-exports the public package API the routes import and owns the plugin root, injecting it into the
worker modules. Install and reconfigure live in `installer.py`; the batched-apply engine in
`batch.py` drives the batched update (`updater.py`) and the batched install (`installer_batch.py`);
the uninstall family in `uninstaller.py`, and the deactivate/teardown lifecycle in `lifecycle.py`;
recover still lives here pending its own decision (it currently stays as facade wiring, like the
recover() precedent).

A .b3 package is a zip of manifest.json plus the plugin file tree. Signature verification is
deferred until packages are signed.
"""

from pathlib import Path

from ..data_root import DATA_ROOT
from ..safety import OperationContext, OperationKind
from .batch_progress import ProgressSink  # noqa: F401  re-export for api.routes
from .batch_uninstaller import run_uninstall_batch
from .deactivation import DEACTIVATED_MARKER
from .dependencies import provided_services, topo_sort
from .errors import (
    BlockedActionError,  # noqa: F401  re-export for api.routes
    ConflictError,  # noqa: F401  re-export for api.routes
    DependentsError,  # noqa: F401  re-export for api.routes
    RequirementError,  # noqa: F401  re-export for api.routes
)
from .installer import (
    PhaseListener,  # noqa: F401  re-export for api.routes
    run_install,
)
from .installer_batch import run_install_batch
from .integrity import IntegrityError  # noqa: F401  re-export for api.routes
from .lifecycle import (  # noqa: F401  re-export for api.routes
    deactivate_all,
    teardown,
)
from .manifest import manifest_at
from .plugin_dir import contained_plugin_dir  # noqa: F401  re-export for api.routes
from .print_guard import guard_no_print
from .reconfigurer import run_reconfigure
from .recovery import recover_one, restart_services
from .uninstaller import run_uninstall
from .updater import run_update_batch
from .user_vars import (
    USER_VARS_FILE,  # noqa: F401  re-export for tests
    load_user_vars,  # noqa: F401  re-export for api.routes
    validate_user_vars,  # noqa: F401  re-export for api.routes
)

PLUGIN_ROOT = DATA_ROOT / "usr/local/plugins"


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
    publish: ProgressSink | None = None,
) -> list[dict]:
    return run_update_batch(PLUGIN_ROOT, base_vars, package_paths, vars_by_id, publish)


def install_batch(
    base_vars: dict[str, str],
    package_paths: list[Path],
    vars_by_id: dict[str, dict[str, str]],
    publish: ProgressSink | None = None,
) -> list[dict]:
    return run_install_batch(PLUGIN_ROOT, base_vars, package_paths, vars_by_id, publish)


def recover(vars: dict[str, str]) -> list[dict]:
    """Re-apply all installed, non-deactivated plugins after OTA. Returns per-plugin results."""
    guard_no_print()
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


def uninstall(plugin_id: str, vars: dict[str, str], cascade: bool = False) -> list[str]:
    return run_uninstall(PLUGIN_ROOT, plugin_id, vars, cascade)


def uninstall_batch(
    plugin_ids: list[str], vars: dict[str, str], cascade: bool = False
) -> list[dict]:
    return run_uninstall_batch(PLUGIN_ROOT, plugin_ids, vars, cascade)


