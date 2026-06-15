import pytest

from core import capabilities, jinni_client
from jinni.loader import GenericJinni


def test_generic_jinni_refuses_managed_services() -> None:
    jinni = GenericJinni()
    assert "managed-service" not in jinni.capability_flags()
    with pytest.raises(NotImplementedError):
        jinni.render_service_script({"name": "x", "command": "/bin/true"}, {"BESPOK3D": "/d"})


def test_generic_jinni_hardware_returns_empty_list() -> None:
    assert GenericJinni().hardware() == []


def test_generic_jinni_preferred_registries_returns_empty_list() -> None:
    assert GenericJinni().preferred_registries() == []


def test_generic_jinni_makes_no_klipper_version_claim() -> None:
    assert not hasattr(GenericJinni(), "klipper_version")


def test_klipper_jinni_reports_a_version_string() -> None:
    from jinni import KlipperPrinterJinni
    version = KlipperPrinterJinni().klipper_version()
    assert isinstance(version, str)
    assert len(version) > 0


def test_generic_jinni_installed_plugins_returns_a_dict() -> None:
    assert isinstance(GenericJinni().installed_plugins(), dict)


def test_generic_jinni_firmware_version_returns_unknown() -> None:
    assert GenericJinni().firmware_version() == "unknown"


def test_get_capabilities_returns_complete_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jinni_client, "get_jinni", GenericJinni)
    response = capabilities.get_capabilities()

    assert response.adapter == "generic"
    assert isinstance(response.hardware, list)
    assert isinstance(response.installed, dict)
    assert response.firmware_version == "unknown"
    assert isinstance(response.klipper_version, str)
    assert isinstance(response.preferred_registries, list)
    assert isinstance(response.endpoints, list)
