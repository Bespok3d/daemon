# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The batched-application engine: apply each package's install phases, deferring every core-service
restart so the whole batch restarts once at the end, streaming per-plugin and per-phase progress to
a sink. Two entry points share this engine: the multi-plugin UPDATE (`updater.py`) and the
multi-plugin INSTALL (`installer_batch.py`). They differ only in the operation reported to the
safety net and in install's up-front settling of what the printer will not accept. Batching matters
on the U1: a single op bounces the display compositor once, so installing N display plugins one at a
time rolls the VOP2-wedge dice N times, while one batch bounces it once.
"""

from pathlib import Path

from ..results import SERVICES_PLUGIN_ID
from ..safety import OperationContext, OperationKind
from .batch_one import apply_one
from .batch_plan import BatchPlan
from .batch_progress import BatchProgress
from .batch_rows import failed_result, install_error, settle_after_safety_net
from .dependencies import provided_services
from .installer import PhaseListener
from .left_out import services_already_on_the_printer, skipped_result, why_not_applied
from .recovery import restart_services


def _apply_or_report(
    plugin_root: Path,
    plan: BatchPlan,
    package_path: Path,
    plugin_id: str,
    notify: PhaseListener,
) -> tuple[dict, list[str]]:
    """One plugin's turn, never allowed to end the batch: an error raised before the apply engine
    can contain it still comes back as this plugin's failed result."""
    try:
        return apply_one(
            plugin_root, plan.base_vars, package_path, plan.vars_by_id.get(plugin_id, {}),
            notify,
        )
    except Exception as exc:  # noqa: BLE001 - a pre-apply error must not abort the batch
        return failed_result(plugin_id, install_error(exc), []), []


def _apply_each(
    plugin_root: Path, plan: BatchPlan, progress: BatchProgress, kind: OperationKind,
) -> tuple[list[dict], list[str]]:
    """Apply each package in order (announcing the plugin and streaming its phases), collecting the
    per-plugin results and every deferred restart command for the caller to run once.

    A plugin only gets its turn once the plugins it needs are actually on the printer, decided here
    and now rather than at the start of the call, so a plugin the printer rolled back mid-batch
    takes the plugins that need it out with it instead of leaving them running against a service
    that is not there. This is recover's per-plugin precondition skip, on the install side."""
    results: list[dict] = [
        failed_result(plugin_id, reason, []) for plugin_id, reason in plan.unreadable.items()
    ]
    deferred_restarts: list[str] = []
    satisfied = services_already_on_the_printer(plugin_root, plan.plugin_ids())
    providers = plan.providers_in_batch()
    total = len(plan.specs)
    for index, (package_path, manifest) in enumerate(plan.specs):
        plugin_id = manifest["name"]
        progress.plugin(plugin_id, index, total)
        left_out = why_not_applied(manifest, plan.refused, providers, satisfied, kind)
        if left_out is not None:
            results.append(skipped_result(plugin_id, left_out))
            continue
        result, deferred = _apply_or_report(
            plugin_root, plan, package_path, plugin_id, progress.phase,
        )
        if result["ok"]:
            satisfied.update(provided_services(manifest))
        results.append(result)
        deferred_restarts.extend(deferred)
    return results, deferred_restarts


def run_batch(
    plugin_root: Path, plan: BatchPlan, progress: BatchProgress, kind: OperationKind,
) -> list[dict]:
    """Apply every package with its restart deferred, then run the deduped restarts once through the
    safety net (reported under the given operation kind) and await Klipper + Moonraker healthy."""
    results, deferred_restarts = _apply_each(plugin_root, plan, progress, kind)
    unique_restarts = list(dict.fromkeys(deferred_restarts))
    if not unique_restarts:
        return results
    progress.plugin(SERVICES_PLUGIN_ID, len(plan.specs), len(plan.specs))
    lone_plugin_id = plan.specs[0][1]["name"] if len(plan.specs) == 1 else None
    ctx = OperationContext(kind, plugin_id=lone_plugin_id)
    services_row = restart_services(plugin_root, unique_restarts, plan.base_vars, ctx)

    return [*settle_after_safety_net(results, services_row), services_row]
