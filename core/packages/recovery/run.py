# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Re-apply every installed plugin, in dependency order, reporting each one as it goes."""
from pathlib import Path

from ...results import SERVICES_PLUGIN_ID
from ...safety import OperationContext, OperationKind
from ..batch_progress import BatchProgress, ProgressSink, make_progress
from ..deactivation import DEACTIVATED_MARKER
from ..dependencies import provided_services, topo_sort
from ..manifest import manifest_at
from ..print_guard import guard_no_print
from ..repair import restore_printer_state
from .reapply import ServiceLedger, recover_one
from .restart import restart_services


def recoverable_plugin_dirs(plugin_root: Path) -> list[Path]:
    """Everything installed that recovery puts back: not deactivated, still carrying a manifest."""
    return [
        plugin_dir for plugin_dir in plugin_root.iterdir()
        if plugin_dir.is_dir()
        and (plugin_dir / "manifest.json").exists()
        and not (plugin_dir / DEACTIVATED_MARKER).exists()
    ]


def _services_the_installed_set_provides(manifests: dict[Path, dict]) -> set[str]:
    return {service for manifest in manifests.values() for service in provided_services(manifest)}


def _recover_in_order(
    ordered: list[Path],
    manifests: dict[Path, dict],
    services: ServiceLedger,
    vars: dict[str, str],
    progress: BatchProgress,
) -> tuple[list[dict], list[str]]:
    """Re-apply each plugin in dependency order, naming it as it starts so the app can show the user
    where recovery is. Returns the per-plugin results and the restarts held back to the end."""
    results: list[dict] = []
    deferred_restarts: list[str] = []
    for position, plugin_dir in enumerate(ordered):
        progress.plugin(plugin_dir.name, position, len(ordered))
        result, deferred = recover_one(plugin_dir, manifests[plugin_dir], services, vars, progress.phase)  # noqa: E501
        results.append(result)
        if result["ok"]:
            deferred_restarts.extend(deferred)

    return results, deferred_restarts


def run_recovery(
    data_root: Path, plugin_root: Path, vars: dict[str, str], publish: ProgressSink | None = None
) -> list[dict]:
    """Make the printer sound, then re-apply all installed, non-deactivated plugins (after an OTA,
    or after anything else left the printer half done). Every problem `selfcheck` reports is one
    this clears. Announces its own plan first: unlike a batch, the set and its order are decided
    here, from what is on the printer. Returns per-plugin results."""
    guard_no_print()
    restore_printer_state(data_root, plugin_root, vars)
    if not plugin_root.exists():
        return []
    plugin_dirs = recoverable_plugin_dirs(plugin_root)
    if not plugin_dirs:
        return []
    ordered = topo_sort(plugin_dirs)
    manifests = {plugin_dir: manifest_at(plugin_dir) for plugin_dir in ordered}
    services = ServiceLedger(set(), _services_the_installed_set_provides(manifests))
    progress = make_progress(publish)
    progress.plan([plugin_dir.name for plugin_dir in ordered])
    results, deferred_restarts = _recover_in_order(ordered, manifests, services, vars, progress)
    unique_restarts = list(dict.fromkeys(deferred_restarts))
    if unique_restarts:
        progress.plugin(SERVICES_PLUGIN_ID, len(ordered), len(ordered))
        results.append(restart_services(plugin_root, unique_restarts, vars, OperationContext(OperationKind.RECOVER)))  # noqa: E501

    return results
