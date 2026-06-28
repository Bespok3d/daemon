"""The batched-application engine: apply each package's install phases, deferring every core-service
restart so the whole batch restarts once at the end, streaming per-plugin and per-phase progress to
a sink. Two entry points share this engine: the multi-plugin UPDATE (`updater.py`) and the
multi-plugin INSTALL (`installer_batch.py`). They differ only in the operation reported to the
safety net and in install's up-front conflict check. Batching matters on the U1: a single op bounces
the display compositor once, so installing N display plugins one at a time rolls the VOP2-wedge dice
N times, while one batch bounces it once.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..results import SERVICES_PLUGIN_ID, item, phase
from ..safety import OperationContext, OperationKind
from .archive import read_manifest, unpack_package
from .deactivation import deactivate_plugin, finalize_install_outcome
from .installer import PhaseListener, apply_install_deferred
from .print_guard import guard_batch_no_print
from .recovery import restart_services
from .user_vars import persist_user_vars, with_plugin_venv

Spec = tuple[Path, dict]

# One sink that receives each batch-progress event as a dict (the install-progress hub's publish).
ProgressSink = Callable[[dict], None]


@dataclass(frozen=True)
class BatchPlan:
    """One batch's inputs, which always travel together through the apply-and-restart engine: the
    shared base vars, the (path, manifest) specs in apply order, and the per-plugin user vars."""

    base_vars: dict[str, str]
    specs: list[Spec]
    vars_by_id: dict[str, dict[str, str]]


def _noop_progress(_event: dict) -> None:
    return None


class BatchProgress:
    """Shapes a batch's live events onto one sink. A `plugin` event names the plugin a batch is
    starting (zero-based index of total); the deferred restart is announced as a `plugin` under
    SERVICES_PLUGIN_ID with index == total. A `phase` event carries a finished install phase.
    """

    def __init__(self, publish: ProgressSink) -> None:
        self._publish = publish

    def plugin(self, plugin_id: str, index: int, total: int) -> None:
        self._publish({"type": "plugin", "plugin_id": plugin_id, "index": index, "total": total})

    def phase(self, finished_phase: dict) -> None:
        self._publish({"type": "phase", "phase": finished_phase})


def make_progress(publish: ProgressSink | None) -> BatchProgress:
    return BatchProgress(publish or _noop_progress)


def _failed_result(plugin_id: str, reason: str, log: list[dict]) -> dict:
    return {"plugin_id": plugin_id, "ok": False, "skipped": False, "reason": reason, "log": log}


def _apply_one(
    plugin_root: Path,
    base_vars: dict[str, str],
    package_path: Path,
    user_vars: dict[str, str],
    notify: PhaseListener,
) -> tuple[dict, list[str]]:
    """Apply one package's install, deferring its restart. A failure is contained to this plugin
    (recover_one's pattern): a raised or failed-phase apply deactivates it and returns a failed
    result, so the rest of the batch still completes."""
    manifest, plugin_dir, file_count = unpack_package(plugin_root, package_path)
    plugin_id = manifest["name"]
    full_vars = with_plugin_venv({**base_vars, **user_vars}, plugin_id)
    persist_user_vars(plugin_dir, user_vars)
    extract = phase("extract", "Unpack", [item(f"Extracted {file_count} files", ok=True)])
    notify(extract)
    try:
        phases, deferred = apply_install_deferred(
            plugin_root, plugin_dir, manifest, full_vars, notify,
        )
    except Exception as exc:  # noqa: BLE001 - one plugin's apply error must NOT abort the batch
        reason = f"install error: {type(exc).__name__}: {exc}"
        deactivate_plugin(plugin_dir, full_vars, reason)
        return _failed_result(plugin_id, reason, [extract]), []
    log = [extract, *phases]
    finalize_install_outcome(plugin_dir, full_vars, log)
    ok = all(logged_phase["ok"] for logged_phase in log)
    reason = "" if ok else "update phase failed"
    result = {"plugin_id": plugin_id, "ok": ok, "skipped": False, "reason": reason, "log": log}
    return result, (deferred if ok else [])


def _apply_each(
    plugin_root: Path, plan: BatchPlan, progress: BatchProgress,
) -> tuple[list[dict], list[str]]:
    """Apply each package in order (announcing the plugin and streaming its phases), collecting the
    per-plugin results and every deferred restart command for the caller to run once."""
    results: list[dict] = []
    deferred_restarts: list[str] = []
    total = len(plan.specs)
    for index, (package_path, manifest) in enumerate(plan.specs):
        plugin_id = manifest["name"]
        progress.plugin(plugin_id, index, total)
        user_vars = plan.vars_by_id.get(plugin_id, {})
        try:
            result, deferred = _apply_one(
                plugin_root, plan.base_vars, package_path, user_vars, progress.phase,
            )
        except Exception as exc:  # noqa: BLE001 - a pre-apply error must not abort the batch
            reason = f"install error: {type(exc).__name__}: {exc}"
            result, deferred = _failed_result(plugin_id, reason, []), []
        results.append(result)
        deferred_restarts.extend(deferred)
    return results, deferred_restarts


def run_batch(
    plugin_root: Path, plan: BatchPlan, progress: BatchProgress, kind: OperationKind,
) -> list[dict]:
    """Apply every package with its restart deferred, then run the deduped restarts once through the
    safety net (reported under the given operation kind) and await Klipper + Moonraker healthy."""
    results, deferred_restarts = _apply_each(plugin_root, plan, progress)
    unique_restarts = list(dict.fromkeys(deferred_restarts))
    if unique_restarts:
        progress.plugin(SERVICES_PLUGIN_ID, len(plan.specs), len(plan.specs))
        only = plan.specs[0][1]["name"] if len(plan.specs) == 1 else None
        ctx = OperationContext(kind, plugin_id=only)
        results.append(restart_services(plugin_root, unique_restarts, plan.base_vars, ctx))
    return results


def plan_batch(
    base_vars: dict[str, str],
    package_paths: list[Path],
    vars_by_id: dict[str, dict[str, str]],
) -> BatchPlan:
    """Read each package's manifest and refuse the batch up front if any operation would run during
    a print. Shared by both batch entry points, so neither can skip the print-safety gate."""
    specs = [(package_path, read_manifest(package_path)) for package_path in package_paths]
    guard_batch_no_print([manifest for _, manifest in specs])
    return BatchPlan(base_vars, specs, vars_by_id)
