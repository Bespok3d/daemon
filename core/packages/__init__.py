# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Package-operations facade.

Re-exports the public package API the routes import and owns the plugin root, injecting it into the
worker modules. Install and reconfigure live in `installer.py`; the batched-apply engine in
`batch.py` drives the batched update (`updater.py`) and the batched install (`installer_batch.py`);
the uninstall family in `uninstaller.py`, the deactivate/teardown lifecycle in `lifecycle.py`, and
the post-OTA re-apply in `recovery/run.py`.

A .b3 package is a zip of manifest.json plus the plugin file tree. Signature verification is
deferred until packages are signed.
"""

from pathlib import Path

from ..data_root import DATA_ROOT
from .batch_progress import ProgressSink  # noqa: F401  re-export for api.routes
from .batch_uninstaller import run_uninstall_batch
from .deactivation import DEACTIVATED_MARKER  # noqa: F401  re-export for api.routes
from .dependencies import (  # noqa: F401  re-export for api.routes
    provided_services,
    topo_sort,
)
from .errors import (
    BlockedActionError,  # noqa: F401  re-export for api.routes
    ConflictError,  # noqa: F401  re-export for api.routes
    DependentsError,  # noqa: F401  re-export for api.routes
    IncompatiblePairError,  # noqa: F401  re-export for api.routes
    RequirementError,  # noqa: F401  re-export for api.routes
)
from .installer import (
    PhaseListener,  # noqa: F401  re-export for api.routes
    run_install,
)
from .installer_batch import run_install_batch
from .integrity import IntegrityError  # noqa: F401  re-export for api.routes
from .lifecycle import (  # noqa: F401  re-export for api.routes
    GLOBAL_DEACTIVATED_MARKER,
    deactivate_all,
    teardown,
)
from .manifest import manifest_at  # noqa: F401  re-export for api.routes
from .plugin_dir import contained_plugin_dir  # noqa: F401  re-export for api.routes
from .print_guard import guard_no_print  # noqa: F401  re-export for api.routes
from .reconfigurer import run_reconfigure
from .recovery import (  # noqa: F401  re-export for api.routes
    recover_one,
    restart_services,
    run_recovery,
)
from .uninstaller import run_uninstall
from .updater import run_update_batch
from .user_vars import (
    USER_VARS_FILE,  # noqa: F401  re-export for tests
    load_user_vars,  # noqa: F401  re-export for api.routes
    user_vars_as_text,  # noqa: F401  re-export for api.routes
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


def recover(vars: dict[str, str], publish: ProgressSink | None = None) -> list[dict]:
    return run_recovery(DATA_ROOT, PLUGIN_ROOT, vars, publish)


def uninstall(plugin_id: str, vars: dict[str, str], cascade: bool = False) -> list[str]:
    return run_uninstall(PLUGIN_ROOT, plugin_id, vars, cascade)


def uninstall_batch(
    plugin_ids: list[str], vars: dict[str, str], cascade: bool = False
) -> list[dict]:
    return run_uninstall_batch(PLUGIN_ROOT, plugin_ids, vars, cascade)


