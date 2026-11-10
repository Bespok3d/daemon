# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Re-apply every installed plugin, in dependency order, reporting each one as it goes."""
from pathlib import Path

from ...results import SERVICES_PLUGIN_ID
from ...safety import OperationContext, OperationKind
from ..batch_progress import BatchProgress, ProgressSink, make_progress
from ..batch_rows import settle_after_safety_net
from ..deactivation import DEACTIVATED_MARKER
from ..dependencies import provided_services
from ..dependency_order import order_by_dependency
from ..manifest import installed_manifest_dirs, installed_manifests, readable_manifest
from ..print_guard import guard_no_print
from ..repair import restore_printer_state
from .put_back import plugins_to_put_back
from .reapply import ServiceLedger, record_failure, recover_one
from .reboot_replaces import forget_restarts_left_to_reboot, leave_restarts_to_reboot
from .restart import restart_services
from .stale_originals import drop_kept_originals, settle_kept_originals_of_switched_off
from .turn_order import next_to_recover


def recoverable_plugin_dirs(plugin_root: Path) -> list[Path]:
    """Everything installed that recovery puts back: the plugins that are on, and the ones the
    safety net switched off (`put_back`)."""
    switched_on = [plugin_dir for plugin_dir in installed_manifest_dirs(plugin_root)
                   if not (plugin_dir / DEACTIVATED_MARKER).exists()]
    return [*switched_on, *plugins_to_put_back(plugin_root)]


def _staying_off(plugin_root: Path, put_back: list[Path]) -> list[Path]:
    return [plugin_dir for plugin_dir in installed_manifest_dirs(plugin_root)
            if (plugin_dir / DEACTIVATED_MARKER).exists() and plugin_dir not in put_back]


UNREADABLE_MANIFEST = "manifest unreadable: reinstall the plugin"


def _readable_manifests_and_torn(plugin_dirs: list[Path]) -> tuple[dict[Path, dict], list[Path]]:
    """The plugins recovery can re-apply, each with its manifest, and separately the ones whose
    manifest cannot be read (a power cut mid write). One torn manifest is one plugin's problem: the
    rest of the printer is recovered around it."""
    read = {plugin_dir: readable_manifest(plugin_dir) for plugin_dir in plugin_dirs}
    usable = {plugin_dir: manifest for plugin_dir, manifest in read.items() if manifest is not None}
    return usable, [plugin_dir for plugin_dir in plugin_dirs if plugin_dir not in usable]


def _switch_off_torn(plugin_dir: Path, vars: dict[str, str]) -> dict:
    """Switch off a plugin whose manifest cannot be read. Without it no kept original can be
    checked against the printer's file, so after a firmware update any of them may be the old
    firmware's: they are dropped before anything can write them back."""
    drop_kept_originals(plugin_dir)
    return record_failure(plugin_dir, vars, UNREADABLE_MANIFEST, {}, [])


def _services_installed_plugins_provide(plugin_root: Path) -> set[str]:
    """Switched-off plugins count: a plugin whose provider stays off must go off too, not be wired
    back to stop the printer at the next start."""
    manifests = installed_manifests(plugin_root).values()
    return {service for manifest in manifests for service in provided_services(manifest)}


def _recover_in_order(
    ordered: list[Path],
    manifests: dict[Path, dict],
    services: ServiceLedger,
    vars: dict[str, str],
    progress: BatchProgress,
) -> tuple[list[dict], list[str]]:
    """Re-apply each plugin in dependency order, naming it by its place in the announced plan as it
    starts and saying how its turn ended, so the app can show the user where recovery is. Returns
    the per-plugin results and the restarts held back to the end."""
    plan_position = {plugin_dir: position for position, plugin_dir in enumerate(ordered)}
    results: list[dict] = []
    deferred_restarts: list[str] = []
    waiting = ordered
    while waiting:
        plugin_dir = next_to_recover(waiting, manifests, services)
        waiting = [other for other in waiting if other != plugin_dir]
        progress.plugin(plugin_dir.name, plan_position[plugin_dir], len(ordered))
        result, deferred = recover_one(plugin_dir, manifests[plugin_dir], services, vars, progress.phase)  # noqa: E501
        progress.outcome(result)
        results.append(result)
        if result["ok"]:
            deferred_restarts.extend(deferred)

    return results, deferred_restarts


def _services_row(data_root: Path, plugin_root: Path, held_restarts: list[str],
                  vars: dict[str, str], reboot_follows: bool) -> dict:
    if reboot_follows:
        return leave_restarts_to_reboot(data_root, held_restarts)
    recover_context = OperationContext(OperationKind.RECOVER)
    return restart_services(plugin_root, held_restarts, vars, recover_context)


def run_recovery(
    data_root: Path, plugin_root: Path, vars: dict[str, str], publish: ProgressSink | None = None,
    reboot_follows: bool = False,
) -> list[dict]:
    """Make the printer sound, then re-apply the installed plugins that are on and the ones the
    safety net switched off (after an OTA, or after anything else left the printer half done).
    Every problem `selfcheck` reports is one this clears. Announces its own plan first: unlike a
    batch, the set and its order are decided here, from what is on the printer. Returns per-plugin
    results. `reboot_follows` is the caller's promise to reboot the printer right after: the reboot
    does the services restart, and the caller asks for the safety net check once the printer is
    back (`check_after_reboot`)."""
    guard_no_print()
    forget_restarts_left_to_reboot(data_root)
    restore_printer_state(data_root, plugin_root, vars)
    if not plugin_root.exists():
        return []
    plugin_dirs = recoverable_plugin_dirs(plugin_root)
    unchecked_results = settle_kept_originals_of_switched_off(
        _staying_off(plugin_root, plugin_dirs), vars)
    if not plugin_dirs:
        return unchecked_results
    manifests, torn = _readable_manifests_and_torn(plugin_dirs)
    torn_results = [_switch_off_torn(plugin_dir, vars) for plugin_dir in torn]
    ordered = order_by_dependency(list(manifests), manifests)
    services = ServiceLedger(set(), _services_installed_plugins_provide(plugin_root))
    progress = make_progress(publish)
    progress.plan([plugin_dir.name for plugin_dir in ordered])
    recovered, deferred_restarts = _recover_in_order(ordered, manifests, services, vars, progress)
    results = [*unchecked_results, *torn_results, *recovered]
    unique_restarts = list(dict.fromkeys(deferred_restarts))
    if not unique_restarts:
        return results
    progress.plugin(SERVICES_PLUGIN_ID, len(ordered), len(ordered))
    services_row = _services_row(data_root, plugin_root, unique_restarts, vars, reboot_follows)

    return [*settle_after_safety_net(results, services_row, progress), services_row]
