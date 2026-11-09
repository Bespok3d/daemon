# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The order plugins are applied in: every provider before the plugins that need its service, for
recover after a firmware update and for a batch of packages.
"""

from itertools import product
from pathlib import Path
from typing import Any

from .dependencies import provided_services, required_services
from .manifest import readable_manifest

ServiceMap = dict[Path, set[str]]


def _comes_back_without(
    missing_service: str, waits_on: ServiceMap, provides: ServiceMap,
) -> set[Path]:
    """The plugins that can come back while nothing here gives `missing_service` yet."""
    back: set[Path] = set()
    while True:
        available = {service for plugin_dir in back for service in provides[plugin_dir]}
        ready = {plugin_dir for plugin_dir, waits in waits_on.items()
                 if plugin_dir not in back and waits <= available - {missing_service}}
        if not ready:
            return back
        back = back | ready


def _service_maps(
    plugin_dirs: list[Path], manifests: dict[Path, dict[str, Any]],
) -> tuple[ServiceMap, ServiceMap]:
    """What each plugin gives, and which of the services given here it needs."""
    provides = {plugin_dir: set(provided_services(manifests[plugin_dir])) for plugin_dir in plugin_dirs}  # noqa: E501
    given_here = {service for services in provides.values() for service in services}
    waits_on = {plugin_dir: set(required_services(manifests[plugin_dir])) & given_here for plugin_dir in plugin_dirs}  # noqa: E501
    return provides, waits_on


def _dependency_edges(
    plugin_dirs: list[Path], provides: ServiceMap, waits_on: ServiceMap,
) -> list[tuple[Path, Path]]:
    """Each (provider, dependent) pair the order keeps. A dependent waits for every plugin that can
    be the first to bring back a service it needs. A provider that comes back only once that service
    is back from someone else is never the first, so nobody waits for it."""
    given_here = {service for services in provides.values() for service in services}
    first_back = {service: _comes_back_without(service, waits_on, provides) for service in given_here}  # noqa: E501
    return [(provider, dependent) for dependent, provider in product(plugin_dirs, plugin_dirs)
            if _can_bring_back_first(provider, waits_on[dependent] & provides[provider],
                                     first_back)]


def _can_bring_back_first(provider: Path, services_it_gives_the_dependent: set[str],
                          first_back: dict[str, set[Path]]) -> bool:
    return any(provider in first_back[service] for service in services_it_gives_the_dependent)


def _build_dep_graph(
    plugin_dirs: list[Path], provides: ServiceMap, waits_on: ServiceMap,
) -> tuple[dict[Path, int], dict[Path, list[Path]]]:
    in_degree: dict[Path, int] = {plugin_dir: 0 for plugin_dir in plugin_dirs}
    reverse_deps: dict[Path, list[Path]] = {plugin_dir: [] for plugin_dir in plugin_dirs}
    for provider, dependent in _dependency_edges(plugin_dirs, provides, waits_on):
        in_degree[dependent] += 1
        reverse_deps[provider].append(dependent)
    return in_degree, reverse_deps


def _decrement_and_enqueue(
    dependents: list[Path],
    in_degree: dict[Path, int],
    queue: list[Path],
) -> None:
    for dependent in dependents:
        in_degree[dependent] -= 1
        if in_degree[dependent] == 0:
            queue.append(dependent)


def _released_from_a_cycle(nodes: list[Path], ordered: list[Path], provides: ServiceMap,
                           waits_on: ServiceMap) -> list[Path]:
    """When a service has a second provider, plugins can end up waiting for each other, which stops
    the order. The first plugin that already has a provider placed for every service it needs is let
    through: it only waits for a second provider. With none, the plugins left keep the given
    order."""
    placed_services = {service for node in ordered for service in provides[node]}
    return [node for node in nodes
            if node not in ordered and waits_on[node] <= placed_services][:1]


def order_by_dependency(nodes: list[Path], manifests: dict[Path, dict[str, Any]]) -> list[Path]:
    """Providers before the plugins that require them, keeping the given order between unrelated
    plugins. The nodes are paths the caller already holds a manifest for: installed plugin dirs for
    recover, staged package files for a batch. A cycle no plugin can be let out of leaves its
    members in the given order."""
    provides, waits_on = _service_maps(nodes, manifests)
    in_degree, reverse_deps = _build_dep_graph(nodes, provides, waits_on)
    queue = [node for node in nodes if in_degree[node] == 0]
    ordered: list[Path] = []
    while queue:
        node = queue.pop(0)
        ordered.append(node)
        _decrement_and_enqueue(reverse_deps[node], in_degree, queue)
        if not queue:
            queue = _released_from_a_cycle(nodes, ordered, provides, waits_on)
            # A released plugin still counts providers not placed yet; from 0 those counts go
            # negative, so placing them later never queues it a second time.
            in_degree.update({released: 0 for released in queue})

    remaining = [node for node in nodes if node not in ordered]
    return ordered + remaining


def topo_sort(plugin_dirs: list[Path]) -> list[Path]:
    return order_by_dependency(plugin_dirs, {plugin_dir: readable_manifest(plugin_dir) or {} for plugin_dir in plugin_dirs})  # noqa: E501
