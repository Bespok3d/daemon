import json
from pathlib import Path

from core import packages
from core.packages import dependencies


def write_plugin(
    root: Path,
    name: str,
    provides: list[str] | None = None,
    depends: list[str] | None = None,
    conflicts: list[str] | None = None,
) -> Path:
    plugin_dir = root / name
    plugin_dir.mkdir(parents=True)
    manifest = {
        "name": name,
        "version": "1.0.0",
        "provides": provides or [],
        "depends": depends or [],
        "conflicts": conflicts or [],
    }
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest))
    return plugin_dir


def test_orchestrator_reexports_the_dependency_helpers() -> None:
    assert packages.installed_dependents is dependencies.installed_dependents
    assert packages.installed_conflicts is dependencies.installed_conflicts
    assert packages.topo_sort is dependencies.topo_sort
    assert packages.provided_services is dependencies.provided_services


def test_provided_services_reads_both_forms() -> None:
    assert dependencies.provided_services({"provides": ["svc"]}) == ["svc"]
    assert dependencies.provided_services({"provides": [{"service": "svc"}]}) == ["svc"]


def test_required_services_reads_require_then_legacy_depends() -> None:
    assert dependencies.required_services({"require": [{"service": "svc"}]}) == ["svc"]
    assert dependencies.required_services({"depends": ["svc@>=1.0", "base"]}) == ["svc"]


def test_installed_dependents_lists_requirers_of_a_provided_service(tmp_path: Path) -> None:
    write_plugin(tmp_path, "provider", provides=["svc"])
    write_plugin(tmp_path, "consumer", depends=["svc@>=1.0"])
    assert dependencies.installed_dependents(tmp_path, "provider") == ["consumer"]
    assert dependencies.installed_dependents(tmp_path, "consumer") == []


def test_installed_conflicts_is_symmetric(tmp_path: Path) -> None:
    write_plugin(tmp_path, "existing", conflicts=["incoming"])
    incoming_manifest = {"name": "incoming", "conflicts": []}
    assert dependencies.installed_conflicts(tmp_path, "incoming", incoming_manifest) == ["existing"]


def test_topo_sort_places_providers_before_requirers(tmp_path: Path) -> None:
    consumer = write_plugin(tmp_path, "consumer", depends=["svc@>=1.0"])
    provider = write_plugin(tmp_path, "provider", provides=["svc"])
    ordered = dependencies.topo_sort([consumer, provider])
    assert ordered.index(provider) < ordered.index(consumer)
