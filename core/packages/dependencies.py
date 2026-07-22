"""The plugin dependency graph: which installed plugins provide and require which services,
who depends on or conflicts with whom, and the topological order recover applies them in.

Reads the service model out of each manifest; the manifest IO itself lives in `.manifest`.
"""

from pathlib import Path
from typing import Any

from .deactivation import DEACTIVATED_MARKER
from .manifest import installed_manifest_dirs, manifest_at


def provided_services(manifest: dict) -> list[str]:
    """Service names a manifest provides, in either the service-model or legacy flat form."""
    provides = manifest.get("provides", [])
    return [item["service"] if isinstance(item, dict) else item for item in provides]


def required_services(manifest: dict) -> list[str]:
    """Service names a manifest requires, from `require: [{service}]` or legacy `depends`.

    A legacy `depends` entry pins a version (`svc@>=1.0`); the service name is the part before `@`.
    """
    requires = manifest.get("require")
    if requires is not None:
        return [requirement["service"] for requirement in requires]
    legacy = [dependency.split("@")[0] for dependency in manifest.get("depends", [])]
    return [service for service in legacy if service != "base"]


def _depends_on_any(plugin_dir: Path, services: set[str]) -> bool:
    declared = set(required_services(manifest_at(plugin_dir)))
    return bool(declared & services)


def installed_dependents(plugin_root: Path, plugin_id: str) -> list[str]:
    """Installed plugins that depend on a service the target plugin provides."""
    target_dir = plugin_root / plugin_id
    if not (target_dir / "manifest.json").exists():
        return []
    provided = set(provided_services(manifest_at(target_dir)))
    if not provided:
        return []
    others = [plugin_dir for plugin_dir in installed_manifest_dirs(plugin_root) if plugin_dir != target_dir]  # noqa: E501
    return [plugin_dir.name for plugin_dir in others if _depends_on_any(plugin_dir, provided)]


def installed_provided_services(plugin_root: Path, being_applied: frozenset[str]) -> set[str]:
    """Every service provided by an installed, non-deactivated plugin, ignoring the plugins named in
    `being_applied` (the packages this call is applying, whose freshly-unpacked dirs are already
    present and must not count as providers of what the call itself has yet to deliver)."""
    active = [
        plugin_dir for plugin_dir in installed_manifest_dirs(plugin_root)
        if plugin_dir.name not in being_applied and not (plugin_dir / DEACTIVATED_MARKER).exists()
    ]
    return {service for plugin_dir in active for service in provided_services(manifest_at(plugin_dir))}  # noqa: E501


def unsatisfied_requirements(
    plugin_root: Path, plugin_id: str, manifest: dict, also_provided: frozenset[str] = frozenset(),
) -> list[str]:
    """The services a package requires that no installed, non-deactivated plugin provides.
    `also_provided` covers the batch case, where a sibling package supplies a required service."""
    available = installed_provided_services(plugin_root, frozenset([plugin_id])) | also_provided
    return sorted(service for service in required_services(manifest) if service not in available)


def installed_conflicts(plugin_root: Path, plugin_id: str, manifest: dict) -> list[str]:
    """Installed plugins that this package excludes, or that exclude this package."""
    declared = set(manifest.get("conflicts", []))
    others = [
        plugin_dir for plugin_dir in installed_manifest_dirs(plugin_root)
        if plugin_dir.name != plugin_id
    ]
    clashing = {
        plugin_dir.name for plugin_dir in others
        if plugin_dir.name in declared or plugin_id in manifest_at(plugin_dir).get("conflicts", [])
    }
    return sorted(clashing)


def _record_dep_edge(
    dependent: Path,
    service: str,
    provides_map: dict[str, Path],
    in_degree: dict[Path, int],
    reverse_deps: dict[Path, list[Path]],
) -> None:
    if service not in provides_map or provides_map[service] == dependent:
        return
    provider = provides_map[service]
    in_degree[dependent] += 1
    reverse_deps[provider].append(dependent)


def _build_dep_graph(
    plugin_dirs: list[Path],
    manifests: dict[Path, dict[str, Any]],
    provides_map: dict[str, Path],
) -> tuple[dict[Path, int], dict[Path, list[Path]]]:
    in_degree: dict[Path, int] = {plugin_dir: 0 for plugin_dir in plugin_dirs}
    reverse_deps: dict[Path, list[Path]] = {plugin_dir: [] for plugin_dir in plugin_dirs}
    for plugin_dir in plugin_dirs:
        for service in required_services(manifests[plugin_dir]):
            _record_dep_edge(plugin_dir, service, provides_map, in_degree, reverse_deps)
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


def order_by_dependency(nodes: list[Path], manifests: dict[Path, dict[str, Any]]) -> list[Path]:
    """Providers before the plugins that require them, keeping the given order between unrelated
    plugins. The nodes are paths the caller already holds a manifest for: installed plugin dirs for
    recover, staged package files for a batch. A cycle leaves its members in the given order."""
    provides_map: dict[str, Path] = {
        service: node
        for node, manifest in manifests.items()
        for service in provided_services(manifest)
    }
    in_degree, reverse_deps = _build_dep_graph(nodes, manifests, provides_map)
    queue = [node for node in nodes if in_degree[node] == 0]
    ordered: list[Path] = []
    while queue:
        node = queue.pop(0)
        ordered.append(node)
        _decrement_and_enqueue(reverse_deps[node], in_degree, queue)

    remaining = [node for node in nodes if node not in ordered]
    return ordered + remaining


def topo_sort(plugin_dirs: list[Path]) -> list[Path]:
    return order_by_dependency(plugin_dirs, {plugin_dir: manifest_at(plugin_dir) for plugin_dir in plugin_dirs})  # noqa: E501
