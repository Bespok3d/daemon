"""The jinni package is split by concern: the base Jinni interface is composed from one facet module
per concern, each symbol lives in its named room, and the package facade re-exports what the daemon
imports."""


def test_layout_facet_owns_the_path_contract() -> None:
    from jinni.layout import CORE_PATH_KEYS, Layout

    assert "BESPOK3D" in CORE_PATH_KEYS
    assert callable(Layout.paths)
    assert callable(Layout.device_paths)


def test_realization_facet_owns_the_intent_realizers() -> None:
    from jinni.realization import Realization

    assert callable(Realization.placement_destination)
    assert callable(Realization.instrument_destination)
    assert callable(Realization.restart_command)
    assert callable(Realization.startup_control_scripts)


def test_facts_facet_owns_the_reported_target_facts() -> None:
    from jinni.facts import Facts

    assert callable(Facts.hardware)
    assert callable(Facts.firmware_version)
    assert callable(Facts.version)


def test_probing_facet_owns_the_live_reads_and_the_gate() -> None:
    from jinni.probing import Probing

    assert callable(Probing.port_listening)
    assert callable(Probing.service_get)
    assert callable(Probing.print_active)
    assert callable(Probing.blocked_actions)


def test_plugin_enumeration_lives_in_installed() -> None:
    from jinni.installed import list_deactivated, list_installed

    assert callable(list_installed)
    assert callable(list_deactivated)


def test_base_jinni_composes_the_facets_and_assembles_reports() -> None:
    from jinni.base import Jinni
    from jinni.facts import Facts
    from jinni.layout import Layout
    from jinni.probing import Probing
    from jinni.realization import Realization

    assert Jinni.id == "generic"
    for facet in (Layout, Realization, Facts, Probing):
        assert issubclass(Jinni, facet)
    # the cross-facet assembly stays on the composition root, not in a facet
    assert callable(Jinni.inspect)
    assert callable(Jinni.capabilities)


def test_klipper_path_contract_lives_in_layout() -> None:
    from jinni.layout import KLIPPER_PATH_KEYS

    assert "KLIPPER_SRC" in KLIPPER_PATH_KEYS


def test_klipper_realization_facet_lives_in_realization() -> None:
    from jinni.realization import (
        _KLIPPER_INSTRUMENTS,
        _KLIPPER_PLACEMENTS,
        KlipperRealization,
        Realization,
    )

    assert issubclass(KlipperRealization, Realization)
    assert "klipper-config" in _KLIPPER_PLACEMENTS
    assert "klipper-source" in _KLIPPER_INSTRUMENTS


def test_klipper_facts_facet_lives_in_facts() -> None:
    from jinni.facts import Facts, KlipperFacts

    assert issubclass(KlipperFacts, Facts)
    assert callable(KlipperFacts.klipper_version)


def test_klipper_probing_facet_lives_in_probing() -> None:
    from jinni.layout import Layout
    from jinni.probing import KlipperProbing, Probing

    assert issubclass(KlipperProbing, Probing)
    assert issubclass(KlipperProbing, Layout)
    assert callable(KlipperProbing.print_active)
    assert callable(KlipperProbing.blocked_actions)
    assert callable(KlipperProbing.is_active_print_state)


def test_klipper_health_facet_lives_in_health() -> None:
    from jinni.health import KlipperHealth
    from jinni.layout import Layout
    from jinni.probing import Probing

    assert issubclass(KlipperHealth, Layout)
    assert issubclass(KlipperHealth, Probing)
    assert callable(KlipperHealth.health)


def test_klipper_tier_composes_the_klipper_facets() -> None:
    from jinni.base import Jinni
    from jinni.facts import KlipperFacts
    from jinni.health import KlipperHealth
    from jinni.klipper import KlipperPrinterJinni
    from jinni.probing import KlipperProbing
    from jinni.realization import KlipperRealization

    for facet in (KlipperRealization, KlipperFacts, KlipperProbing, KlipperHealth, Jinni):
        assert issubclass(KlipperPrinterJinni, facet)
    # the klipper path contract is reachable as a class attr (the loader and adapters key off it)
    assert "KLIPPER_SRC" in KlipperPrinterJinni.KLIPPER_PATH_KEYS
    # the cross-facet assembly (klipper-extended reports) stays on the composition root
    assert callable(KlipperPrinterJinni.diagnose)
    assert callable(KlipperPrinterJinni.capabilities)


def test_probes_live_in_inspection() -> None:
    from jinni.inspection import (
        GENERIC_PORTS,
        http_service_get,
        print_state,
        tcp_port_listening,
        visible_endpoints,
    )

    assert callable(tcp_port_listening)
    assert callable(http_service_get)
    assert callable(print_state)
    assert callable(visible_endpoints)
    assert 80 in GENERIC_PORTS


def test_facade_re_exports_the_interface() -> None:
    import jinni
    from jinni.base import Jinni
    from jinni.klipper import KlipperPrinterJinni

    assert jinni.Jinni is Jinni
    assert jinni.KlipperPrinterJinni is KlipperPrinterJinni
    assert "BESPOK3D" in jinni.CORE_PATH_KEYS
    assert "KLIPPER_SRC" in jinni.KLIPPER_PATH_KEYS
    assert callable(jinni.interface_extras)
