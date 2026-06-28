"""The batched multi-plugin UPDATE entry point: apply each package's install phases and restart each
affected service exactly once at the end. The apply-and-defer machinery lives in `batch.py`; this is
the thin entry point that drives it as an update.
"""

from pathlib import Path

from ..safety import OperationKind
from .batch import ProgressSink, make_progress, plan_batch, run_batch


def run_update_batch(
    plugin_root: Path,
    base_vars: dict[str, str],
    package_paths: list[Path],
    vars_by_id: dict[str, dict[str, str]],
    publish: ProgressSink | None = None,
) -> list[dict]:
    """Update several plugins, restarting affected services only once at the end.

    Each package is unpacked and re-applied (templates, symlinks, patches, inline start commands);
    init-script and nginx restarts are deferred, deduped, and run once, then Klipper and Moonraker
    are awaited healthy. Mirrors recover's deferred-restart batching for the update path. Each
    plugin (then the restart step) is announced as it starts, and each phase as it finishes, so a
    watcher sees live progress over the whole batch.
    """
    if not package_paths:
        return []
    progress = make_progress(publish)
    plan = plan_batch(base_vars, package_paths, vars_by_id)
    return run_batch(plugin_root, plan, progress, OperationKind.UPDATE)
