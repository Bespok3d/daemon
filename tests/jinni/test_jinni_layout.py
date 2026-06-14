"""The jinni package is split by concern: each symbol must live in its named room, and the package
facade must re-export the interface the daemon imports."""


def test_base_jinni_and_core_path_keys_live_in_base() -> None:
    from jinni.base import CORE_PATH_KEYS, Jinni

    assert Jinni.id == "generic"
    assert "BESPOK3D" in CORE_PATH_KEYS


def test_klipper_tier_and_klipper_path_keys_live_in_klipper() -> None:
    from jinni.base import Jinni
    from jinni.klipper import KLIPPER_PATH_KEYS, KlipperPrinterJinni

    assert issubclass(KlipperPrinterJinni, Jinni)
    assert "KLIPPER_SRC" in KLIPPER_PATH_KEYS


def test_probes_live_in_inspection() -> None:
    from jinni.inspection import (
        GENERIC_PORTS,
        moonraker_print_state,
        port_open,
        visible_endpoints,
    )

    assert callable(port_open)
    assert callable(moonraker_print_state)
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
