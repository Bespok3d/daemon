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


def test_installed_provided_services_unions_active_providers(tmp_path: Path) -> None:
    write_plugin(tmp_path, "tun-module", provides=["tun"])
    write_plugin(tmp_path, "spoolman", provides=["spoolman"])
    provided = dependencies.installed_provided_services(tmp_path, frozenset(["zerotier"]))
    assert provided == {"tun", "spoolman"}


def test_installed_provided_services_excludes_self_and_deactivated(tmp_path: Path) -> None:
    write_plugin(tmp_path, "zerotier", provides=["zerotier"])
    deactivated = write_plugin(tmp_path, "tun-module", provides=["tun"])
    (deactivated / "deactivated.json").write_text(json.dumps({"reason": "stale kernel module"}))
    assert dependencies.installed_provided_services(tmp_path, frozenset(["zerotier"])) == set()


def test_unsatisfied_requirements_flags_a_missing_service(tmp_path: Path) -> None:
    manifest = {"name": "zerotier", "require": [{"service": "tun"}]}
    assert dependencies.unsatisfied_requirements(tmp_path, "zerotier", manifest) == ["tun"]


def test_unsatisfied_requirements_is_empty_when_an_installed_plugin_provides_it(tmp_path: Path) -> None:  # noqa: E501
    write_plugin(tmp_path, "tun-module", provides=["tun"])
    manifest = {"name": "zerotier", "require": [{"service": "tun"}]}
    assert dependencies.unsatisfied_requirements(tmp_path, "zerotier", manifest) == []


def test_unsatisfied_requirements_honors_also_provided_for_the_batch_case(tmp_path: Path) -> None:
    manifest = {"name": "zerotier", "require": [{"service": "tun"}]}
    assert dependencies.unsatisfied_requirements(tmp_path, "zerotier", manifest, frozenset({"tun"})) == []  # noqa: E501


def test_topo_sort_places_providers_before_requirers(tmp_path: Path) -> None:
    consumer = write_plugin(tmp_path, "consumer", depends=["svc@>=1.0"])
    provider = write_plugin(tmp_path, "provider", provides=["svc"])
    ordered = dependencies.topo_sort([consumer, provider])
    assert ordered.index(provider) < ordered.index(consumer)
