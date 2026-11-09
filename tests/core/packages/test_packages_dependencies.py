# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
import json
from pathlib import Path

from core import packages
from core.packages import dependencies, dependency_order
from core.packages.daemon_services import DAEMON_SERVICES


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
    assert packages.topo_sort is dependency_order.topo_sort
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


def test_the_printer_can_serve_what_its_active_plugins_provide(tmp_path: Path) -> None:
    write_plugin(tmp_path, "tun-module", provides=["tun"])
    write_plugin(tmp_path, "spoolman", provides=["spoolman"])
    provided = dependencies.services_the_printer_can_serve(tmp_path, frozenset(["zerotier"]))
    assert provided == {"tun", "spoolman"} | DAEMON_SERVICES


def test_a_plugin_being_applied_or_deactivated_serves_nothing(tmp_path: Path) -> None:
    write_plugin(tmp_path, "zerotier", provides=["zerotier"])
    deactivated = write_plugin(tmp_path, "tun-module", provides=["tun"])
    (deactivated / "deactivated.json").write_text(json.dumps({"reason": "stale kernel module"}))
    served = dependencies.services_the_printer_can_serve(tmp_path, frozenset(["zerotier"]))
    assert served == set(DAEMON_SERVICES)


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
    ordered = dependency_order.topo_sort([consumer, provider])
    assert ordered.index(provider) < ordered.index(consumer)


def test_topo_sort_puts_a_dependent_after_every_provider_of_its_service(tmp_path: Path) -> None:
    late_provider = write_plugin(tmp_path, "rfid-late", provides=["rfid"], depends=["power@>=1.0"])
    early_provider = write_plugin(tmp_path, "rfid-early", provides=["rfid"])
    dependent = write_plugin(tmp_path, "spool-tags", depends=["rfid@>=1.0"])
    power_plugin = write_plugin(tmp_path, "power", provides=["power"])
    ordered = dependency_order.topo_sort([late_provider, early_provider, dependent, power_plugin])
    assert ordered.index(early_provider) < ordered.index(dependent)
    assert ordered.index(late_provider) < ordered.index(dependent)


def test_topo_sort_is_not_tied_up_by_providers_that_need_the_service_they_give(
    tmp_path: Path,
) -> None:
    """Two readers each give rfid and need it too, so neither can be the first one back. Waiting for
    each other they would form a loop, and a loop lets the tag user through ahead of the reader that
    gives it tags."""
    tag_user = write_plugin(tmp_path, "spool-tags", depends=["tags@>=1.0"])
    tag_reader = write_plugin(tmp_path, "rfid-tags", provides=["rfid", "tags"],
                              depends=["rfid@>=1.0"])
    other_reader = write_plugin(tmp_path, "rfid-other", provides=["rfid"], depends=["rfid@>=1.0"])
    rfid_base = write_plugin(tmp_path, "rfid-base", provides=["rfid"])
    ordered = dependency_order.topo_sort([tag_user, tag_reader, other_reader, rfid_base])
    assert ordered.index(rfid_base) < ordered.index(tag_reader) < ordered.index(tag_user)
    assert ordered.index(rfid_base) < ordered.index(other_reader)


def test_topo_sort_does_not_wait_for_a_provider_that_comes_back_only_after_the_dependent(
    tmp_path: Path,
) -> None:
    """The second rfid reader needs the tag service the dependent gives, so it can only come back
    after the dependent. Waiting for it too would be a loop, and the loop would hold the dependent
    back until the second reader, which is then switched off for the missing tag service."""
    second_reader = write_plugin(tmp_path, "rfid-second", provides=["rfid"], depends=["tags@>=1.0"])
    dependent = write_plugin(tmp_path, "spool-tags", provides=["tags"], depends=["rfid@>=1.0"])
    first_reader = write_plugin(tmp_path, "rfid-first", provides=["rfid"])
    ordered = dependency_order.topo_sort([second_reader, dependent, first_reader])
    assert ordered.index(first_reader) < ordered.index(dependent) < ordered.index(second_reader)


def test_topo_sort_lets_a_dependent_out_of_a_loop_two_providers_make(tmp_path: Path) -> None:
    """The tag reader needs power the relay gives, and the relay needs rfid the tag reader also
    gives, so the two wait for each other. The relay already has the base reader's rfid placed, so
    it goes first, and the tag user still lands after the only plugin that gives it tags."""
    tag_user = write_plugin(tmp_path, "spool-tags", depends=["tags@>=1.0"])
    power_relay = write_plugin(tmp_path, "power-relay", provides=["power"], depends=["rfid@>=1.0"])
    tag_reader = write_plugin(tmp_path, "rfid-tags", provides=["rfid", "tags"],
                              depends=["power@>=1.0"])
    rfid_base = write_plugin(tmp_path, "rfid-base", provides=["rfid"])
    power_base = write_plugin(tmp_path, "power-base", provides=["power"])
    ordered = dependency_order.topo_sort([tag_user, power_relay, tag_reader, rfid_base, power_base])
    assert ordered == [rfid_base, power_base, power_relay, tag_reader, tag_user]
