import pytest

import jinni
from jinni.loader import GenericJinni, _verify_contract, get_jinni

MP = pytest.MonkeyPatch


class _GenericTestJinni(jinni.Jinni):
    def device_paths(self) -> dict[str, str]:
        return {"BESPOK3D_PLUGINS": "/no/such/plugins"}


class _KlipperTestJinni(jinni.KlipperPrinterJinni):
    def device_paths(self) -> dict[str, str]:
        return {key: f"/dev/null/{key}" for key in jinni.KLIPPER_PATH_KEYS}


def test_loader_falls_back_to_generic_without_an_adapter_jinni() -> None:
    assert isinstance(get_jinni(), GenericJinni)


def test_core_paths_are_guaranteed_even_for_a_minimal_jinni() -> None:
    paths = _GenericTestJinni().paths()
    for key in jinni.CORE_PATH_KEYS:
        assert paths.get(key)


def test_base_jinni_makes_no_klipper_assumptions(monkeypatch: MP) -> None:
    monkeypatch.setattr(jinni.Jinni, "port_listening", lambda self, port: True)
    generic = _GenericTestJinni()
    assert not hasattr(generic, "klipper_version")
    assert 7125 not in generic.inspect()["open_ports"]
    assert "moonraker" not in generic.diagnose()


def test_base_inspect_reports_generic_ports_only(monkeypatch: MP) -> None:
    monkeypatch.setattr(jinni.Jinni, "port_listening", lambda self, port: port in (80, 7125))
    result = _GenericTestJinni().inspect()
    assert result["open_ports"] == [80]
    assert result["print_active"] is False
    assert result["state"] == ""


def test_klipper_inspect_reports_moonraker_and_print_state(monkeypatch: MP) -> None:
    monkeypatch.setattr(jinni.Jinni, "port_listening", lambda self, port: port in (80, 7125))
    monkeypatch.setattr(jinni.inspection, "print_state", lambda _socket: "standby")
    result = _KlipperTestJinni().inspect()
    assert result["open_ports"] == [80, 7125]
    assert {"label": "Web UI", "url": "http://{host}"} in result["endpoints"]
    assert {"label": "Moonraker API", "url": "http://{host}:7125"} in result["endpoints"]
    assert result["state"] == "standby"


def test_klipper_inspect_reports_an_active_print(monkeypatch: MP) -> None:
    monkeypatch.setattr(jinni.Jinni, "port_listening", lambda self, port: False)
    monkeypatch.setattr(jinni.inspection, "print_state", lambda _socket: "printing")
    result = _KlipperTestJinni().inspect()
    assert result["open_ports"] == []
    assert result["print_active"] is True


def test_klipper_diagnose_reports_core_service_liveness(monkeypatch: MP) -> None:
    monkeypatch.setattr(jinni.Jinni, "port_listening", lambda self, port: port == 7125)
    diag = _KlipperTestJinni().diagnose()
    assert diag["moonraker"] is True
    assert diag["web"] is False


def test_generic_web_ui_is_superseded_when_a_plugin_serves_the_root() -> None:
    found = jinni.inspection._discovered_endpoints([80, 7125], {"http://{host}"})
    assert found == [{"label": "Moonraker API", "url": "http://{host}:7125"}]


def test_generic_web_ui_shows_when_no_plugin_serves_the_root() -> None:
    found = jinni.inspection._discovered_endpoints([80], set())
    assert found == [{"label": "Web UI", "url": "http://{host}"}]


class _DeviceKlipperJinni(jinni.KlipperPrinterJinni):
    def device_paths(self) -> dict[str, str]:
        return {key: f"/dev/null/{key}" for key in jinni.KLIPPER_PATH_KEYS}

    def restart_command(self, hook: str) -> str | None:
        return {
            "klipper": "/etc/init.d/S60klipper restart",
            "moonraker": "/etc/init.d/S61moonraker restart",
        }.get(hook)


def test_base_jinni_resolves_no_restart_command() -> None:
    assert _GenericTestJinni().restart_command("klipper") is None


class _BadCoreJinni(jinni.Jinni):
    def device_paths(self) -> dict[str, str]:
        return {"BESPOK3D": ""}


class _BadKlipperJinni(jinni.KlipperPrinterJinni):
    def device_paths(self) -> dict[str, str]:
        return {}


def test_verify_contract_rejects_a_missing_core_key() -> None:
    with pytest.raises(ValueError, match="core path variables"):
        _verify_contract(_BadCoreJinni())


def test_verify_contract_rejects_a_klipper_jinni_missing_klipper_keys() -> None:
    with pytest.raises(ValueError, match="klipper path variables"):
        _verify_contract(_BadKlipperJinni())


def test_verify_contract_rejects_a_klipper_jinni_without_restart_commands() -> None:
    with pytest.raises(ValueError, match="restart command"):
        _verify_contract(_KlipperTestJinni())


def test_verify_contract_accepts_a_klipper_jinni_with_restart_commands() -> None:
    _verify_contract(_DeviceKlipperJinni())


def test_a_standard_jinni_reports_no_interface_extras() -> None:
    assert jinni.interface_extras(_KlipperTestJinni()) == []
    assert jinni.interface_extras(_GenericTestJinni()) == []


class _OverreachingJinni(jinni.KlipperPrinterJinni):
    def device_paths(self) -> dict[str, str]:
        return {key: "/x" for key in jinni.KLIPPER_PATH_KEYS}

    def exfiltrate(self) -> str:
        return "extra behaviour beyond the interface"


def test_interface_extras_flags_methods_beyond_the_standard_interface() -> None:
    assert jinni.interface_extras(_OverreachingJinni()) == ["exfiltrate"]


def test_base_version_is_unknown_until_an_adapter_declares_it() -> None:
    assert _GenericTestJinni().version() == "unknown"


def test_klipper_jinni_resolves_klipper_placement_classes() -> None:
    klipper = _KlipperTestJinni()
    assert klipper.placement_destination("klipper-config", "x.cfg") == "$BESPOK3D_KLIPPER/x.cfg"
    assert klipper.placement_destination("klipper-extra", "h.py") == "$KLIPPER_EXTRAS/h.py"
    assert (
        klipper.placement_destination("moonraker-component", "t.py")
        == "$MOONRAKER_COMPONENTS/t.py"
    )


def test_klipper_jinni_resolves_bespok3d_placement_via_the_base_tier() -> None:
    assert _KlipperTestJinni().placement_destination("system-bin", "curl") == "$BESPOK3D/bin/curl"


def test_base_jinni_resolves_bespok3d_placement_classes() -> None:
    assert (
        _GenericTestJinni().placement_destination("web-location", "s.conf")
        == "$BESPOK3D/etc/nginx/locations/s.conf"
    )


def test_base_jinni_refuses_a_klipper_placement_class() -> None:
    with pytest.raises(ValueError, match="unsupported destination class"):
        _GenericTestJinni().placement_destination("klipper-config", "x.cfg")


def test_klipper_jinni_resolves_the_klipper_source_instrument_class() -> None:
    assert (
        _KlipperTestJinni().instrument_destination("klipper-source", "toolhead.py")
        == "$KLIPPER_SRC/toolhead.py"
    )


def test_base_jinni_refuses_any_instrument_class() -> None:
    with pytest.raises(ValueError, match="unsupported instrument class"):
        _GenericTestJinni().instrument_destination("klipper-source", "x.py")


def test_klipper_jinni_refuses_an_unknown_instrument_class() -> None:
    with pytest.raises(ValueError, match="unsupported instrument class"):
        _KlipperTestJinni().instrument_destination("kernel", "x")
