"""The batched multi-plugin INSTALL entry point ("install selected"): apply each package's install
phases and restart each affected service once at the end. The apply-and-defer machinery lives in
`batch.py`; this adds the one thing a fresh install needs over an update, settling which of the
picked packages the printer will not accept, then drives the shared engine as an install. Collapsing
N restarts into one is what keeps a multi-plugin install from bouncing the U1 display compositor
once per display plugin.

Installing several plugins at once is the same thing as installing them one by one, so a package the
printer will not accept costs that package and the plugins that need it, never the rest of the pick.
"""

from dataclasses import replace
from pathlib import Path

from ..safety import OperationKind
from .batch import run_batch
from .batch_plan import Spec, plan_batch
from .batch_progress import ProgressSink, make_progress
from .dependencies import installed_conflicts, provided_services, unsatisfied_requirements


def _conflict_reason(plugin_root: Path, manifest: dict, accepted: list[dict]) -> str | None:
    """The plugins this package cannot live beside: already on the printer, or picked earlier in the
    same call and accepted. Picked earlier wins, exactly as it would if the user had installed them
    in that order one at a time."""
    plugin_id = manifest["name"]
    declared = set(manifest.get("conflicts", []))
    within = {
        other["name"] for other in accepted
        if other["name"] in declared or plugin_id in other.get("conflicts", [])
    }
    clashes = sorted(set(installed_conflicts(plugin_root, plugin_id, manifest)) | within)

    return f"Conflicts with installed plugin(s): {', '.join(clashes)}" if clashes else None


def _requirement_reason(plugin_root: Path, manifest: dict, specs: list[Spec]) -> str | None:
    """The services this package needs that nothing can supply: no installed, non-deactivated plugin
    and no other package in this call. A package whose provider IS in this call is left to the apply
    loop, which knows whether that provider actually landed."""
    plugin_id = manifest["name"]
    siblings_provide = frozenset(
        service for _, other in specs
        if other["name"] != plugin_id
        for service in provided_services(other)
    )
    missing = unsatisfied_requirements(plugin_root, plugin_id, manifest, siblings_provide)

    return f"Requires a plugin that provides: {', '.join(missing)}" if missing else None


def _in_pick_order(specs: list[Spec], package_paths: list[Path]) -> list[Spec]:
    """The packages back in the order the user picked them, undoing the dependency sort the apply
    order needs. Two plugins that exclude each other are settled by which one the user picked first,
    which must not turn on where the dependency sort happened to put them."""
    picked_at = {package_path: position for position, package_path in enumerate(package_paths)}

    return sorted(specs, key=lambda spec: picked_at[spec[0]])


def refused_packages(
    plugin_root: Path, specs: list[Spec], already_refused: dict[str, str],
) -> dict[str, str]:
    """Which of the picked packages the printer will not accept, and the sentence the user is shown
    for each. Settled before anything is written, so a package that cannot work never gets unpacked;
    the plugins that were waiting on one of these are left out by the apply loop, which is the one
    place that decides what is actually on the printer.

    A package the plan already refused keeps its own reason and never counts as installed, so a
    plugin it excludes is not kept out by a plugin that is not going on the printer either."""
    refused: dict[str, str] = dict(already_refused)
    accepted: list[dict] = []
    for _, manifest in specs:
        if manifest["name"] in refused:
            continue
        reason = (
            _conflict_reason(plugin_root, manifest, accepted)
            or _requirement_reason(plugin_root, manifest, specs)
        )
        if reason is None:
            accepted.append(manifest)
            continue
        refused[manifest["name"]] = reason
    return refused


def run_install_batch(
    plugin_root: Path,
    base_vars: dict[str, str],
    package_paths: list[Path],
    vars_by_id: dict[str, dict[str, str]],
    publish: ProgressSink | None = None,
) -> list[dict]:
    """Install several plugins at once, restarting affected services only once at the end.

    The same apply-and-defer engine as the batched update, with two differences: a fresh install
    settles conflicts and requirements first (so "install selected" cannot land two mutually
    exclusive plugins), and the work is reported to the safety net as an install.
    """
    if not package_paths:
        return []
    progress = make_progress(publish)
    plan = plan_batch(base_vars, package_paths, vars_by_id)
    as_picked = _in_pick_order(plan.specs, package_paths)
    settled = replace(plan, refused=refused_packages(plugin_root, as_picked, plan.refused))

    return run_batch(plugin_root, settled, progress, OperationKind.INSTALL)
