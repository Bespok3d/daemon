"""The batched multi-plugin INSTALL entry point ("install selected"): apply each package's install
phases and restart each affected service once at the end. The apply-and-defer machinery lives in
`batch.py`; this adds the one thing a fresh install needs over an update, an up-front conflict gate,
then drives the shared engine as an install. Collapsing N restarts into one is what keeps a
multi-plugin install from bouncing the U1 display compositor once per display plugin.
"""

from pathlib import Path

from ..safety import OperationKind
from .batch import ProgressSink, Spec, make_progress, plan_batch, run_batch
from .dependencies import installed_conflicts
from .errors import ConflictError


def reject_conflicting_installs(plugin_root: Path, specs: list[Spec]) -> None:
    """Refuse the whole batch before touching the disk if any package excludes (or is excluded by)
    an already-installed plugin OR another package in the same batch. Mirrors the single install's
    conflict gate so two mutually-exclusive plugins cannot slip in together."""
    for _, manifest in specs:
        plugin_id = manifest["name"]
        declared = set(manifest.get("conflicts", []))
        within = {
            other["name"] for _, other in specs
            if other["name"] != plugin_id
            and (other["name"] in declared or plugin_id in other.get("conflicts", []))
        }
        clashes = sorted(set(installed_conflicts(plugin_root, plugin_id, manifest)) | within)
        if clashes:
            raise ConflictError(plugin_id, clashes)


def run_install_batch(
    plugin_root: Path,
    base_vars: dict[str, str],
    package_paths: list[Path],
    vars_by_id: dict[str, dict[str, str]],
    publish: ProgressSink | None = None,
) -> list[dict]:
    """Install several plugins at once, restarting affected services only once at the end.

    The same apply-and-defer engine as the batched update, with two differences: a fresh install
    checks conflicts up front (so "install selected" cannot land two mutually-exclusive plugins),
    and the work is reported to the safety net as an install. Packages are applied in the given
    order, so dependencies come before their dependents.
    """
    if not package_paths:
        return []
    progress = make_progress(publish)
    plan = plan_batch(base_vars, package_paths, vars_by_id)
    reject_conflicting_installs(plugin_root, plan.specs)
    return run_batch(plugin_root, plan, progress, OperationKind.INSTALL)
