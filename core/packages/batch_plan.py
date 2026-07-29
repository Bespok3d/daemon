# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a batch is going to do, settled before anything is written: the packages in the order they
will be applied, the vars each one gets, and the ones the printer already said it will not accept.
Split out of `batch.py` so the apply engine holds only the applying.
"""

from dataclasses import dataclass, field
from pathlib import Path

from .archive import read_manifest
from .dependencies import order_by_dependency, provided_services
from .print_guard import guard_batch_no_print
from .user_vars import validate_user_vars

Spec = tuple[Path, dict]


@dataclass(frozen=True)
class BatchPlan:
    """One batch's inputs, which always travel together through the apply-and-restart engine: the
    shared base vars, the (path, manifest) specs in apply order, the per-plugin user vars, and the
    packages the printer already settled it will not accept (plugin id to the reason the user is
    shown). A refused package still travels with the plan so the plugins waiting on it can be told
    what they were waiting for."""

    base_vars: dict[str, str]
    specs: list[Spec]
    vars_by_id: dict[str, dict[str, str]]
    refused: dict[str, str] = field(default_factory=dict)
    unreadable: dict[str, str] = field(default_factory=dict)

    def plugin_ids(self) -> frozenset[str]:
        return frozenset(manifest["name"] for _, manifest in self.specs)

    def providers_in_batch(self) -> dict[str, tuple[str, ...]]:
        """Which plugins in this same batch owe each service, so a plugin that never landed can be
        named to the plugins that needed it. Every provider is kept, not just one, so a service two
        packages both offer is only waited on while neither of them has landed."""
        return {
            service: tuple(
                manifest["name"] for _, manifest in self.specs
                if service in provided_services(manifest)
            )
            for _, offering in self.specs
            for service in provided_services(offering)
        }


def _readable_packages(package_paths: list[Path]) -> tuple[dict[Path, dict], dict[str, str]]:
    """The manifest of every package the daemon can read, and the sentence shown for each one it
    cannot. A file that is not a package the daemon can open costs only itself: uploading it
    alongside five good plugins still installs those five, exactly as picking them one at a time
    would have. The plugin is named after the file the app uploaded, since a package that cannot be
    read cannot say its own name."""
    manifests: dict[Path, dict] = {}
    unreadable: dict[str, str] = {}
    for package_path in package_paths:
        try:
            manifests[package_path] = read_manifest(package_path)
        except Exception as broken:  # noqa: BLE001 - an unreadable file costs only itself
            unreadable[package_path.stem] = f"package could not be read: {broken}"

    return manifests, unreadable


def _rejected_settings(specs: list[Spec], vars_by_id: dict[str, dict[str, str]]) -> dict[str, str]:
    """The plugins whose user-supplied settings the printer will not take, with the same sentence a
    single install shows. One unusable value costs its own plugin and nothing else in the call."""
    rejected: dict[str, str] = {}
    for _, manifest in specs:
        plugin_id = manifest["name"]
        try:
            validate_user_vars(vars_by_id.get(plugin_id, {}))
        except ValueError as unusable_value:
            rejected[plugin_id] = str(unusable_value)

    return rejected


def plan_batch(
    base_vars: dict[str, str],
    package_paths: list[Path],
    vars_by_id: dict[str, dict[str, str]],
) -> BatchPlan:
    """Read each package's manifest and refuse the batch up front if any operation would run during
    a print. Shared by both batch entry points, so neither can skip the print-safety gate, and
    neither lets one unreadable package or one unusable setting cost the rest of the call.

    The packages are put in dependency order, providers before the plugins that need them, so the
    order the user happened to pick them in can never be the reason a plugin is left out."""
    manifests, unreadable = _readable_packages(package_paths)
    guard_batch_no_print(list(manifests.values()))
    ordered = order_by_dependency(list(manifests), manifests)
    specs = [(path, manifests[path]) for path in ordered]

    refused = _rejected_settings(specs, vars_by_id)

    return BatchPlan(base_vars, specs, vars_by_id, refused, unreadable)
