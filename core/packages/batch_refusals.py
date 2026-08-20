# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which of the packages picked for one batch the printer will not accept, settled before a byte
lands.

Applying several plugins at once is the same thing as applying them one by one, so a package the
printer will not accept costs that package and the plugins that need it, never the rest of the pick.
Both batched entry points settle the same way: an install and an update differ in what they do to a
plugin already on the printer, never in what the printer is willing to hold.
"""

from dataclasses import replace
from pathlib import Path

from .batch_plan import BatchPlan, Spec
from .dependencies import installed_conflicts, provided_services, unsatisfied_requirements


def _conflict_reason(plugin_root: Path, manifest: dict, accepted: list[dict]) -> str | None:
    """The plugins this package cannot live beside: already on the printer, or picked earlier in the
    same call and accepted. Picked earlier wins, exactly as it would if the user had applied them
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


def settle_refusals(plugin_root: Path, plan: BatchPlan, package_paths: list[Path]) -> BatchPlan:
    """The plan with every package the printer will not accept already marked refused, judged in
    the order the user picked them."""
    as_picked = _in_pick_order(plan.specs, package_paths)

    return replace(plan, refused=refused_packages(plugin_root, as_picked, plan.refused))
