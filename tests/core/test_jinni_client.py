"""The jinni seam: the daemon's single door to the jinni over the protocol.

These lock the delegation contract: each verb hands off to the (injected) jinni and returns its
serializable result, and the seam never narrows to a printer tier (it asks any jinni, generic or
klipper, the same way). The seam never imports the jinni runtime, so these drive it with the
duck-typed fakes that answer the protocol verbs. The socket path is covered in the klipper-jinni
app's together tests.
"""
from pathlib import Path

import pytest

from core import jinni_client
from tests.fakes import FakeKlipperJinni
from tests.fakes_generic import FakeGenericJinni

KLIPPER_SERVICE = "klipper"
MOONRAKER_SERVICE = "moonraker"


@pytest.fixture
def fake_jinni(monkeypatch: pytest.MonkeyPatch) -> FakeKlipperJinni:
    jinni = FakeKlipperJinni()
    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", lambda: jinni)
    return jinni


def test_paths_delegates(fake_jinni: FakeKlipperJinni) -> None:
    assert jinni_client.paths() == fake_jinni.paths()


def test_restart_command_delegates(fake_jinni: FakeKlipperJinni) -> None:
    assert jinni_client.restart_command("klipper") == fake_jinni.restart_command("klipper")
    assert jinni_client.restart_command("unknown") is None


def test_capability_flags_delegates(fake_jinni: FakeKlipperJinni) -> None:
    assert jinni_client.capability_flags() == fake_jinni.capability_flags()


def test_render_module_script_delegates(fake_jinni: FakeKlipperJinni) -> None:
    kmodule = {"name": "tun", "module": "tun.ko"}
    rendered = jinni_client.render_module_script(kmodule, {})
    assert rendered == fake_jinni.render_module_script(kmodule, {})


def test_device_node_present_delegates(fake_jinni: FakeKlipperJinni, tmp_path: Path) -> None:
    node = tmp_path / "tun"
    node.write_text("")
    assert jinni_client.device_node_present(str(node)) is True
    assert jinni_client.device_node_present(str(tmp_path / "absent")) is False


def test_variant_facts_delegates(fake_jinni: FakeKlipperJinni) -> None:
    facts = jinni_client.variant_facts()
    assert facts == fake_jinni.variant_facts()
    assert set(facts) == {
        "adapter", "firmware_version", "arch", "board_class", "kernel_release", "vermagic"
    }


def test_health_delegates_to_the_loaded_jinni(fake_jinni: FakeKlipperJinni) -> None:
    report = jinni_client.health()
    assert report.services[KLIPPER_SERVICE].ready
    assert report.services[MOONRAKER_SERVICE].detail == "up"
    assert report.healthy is True


def test_blocked_actions_delegates(monkeypatch: pytest.MonkeyPatch, fake_jinni: FakeKlipperJinni) -> None:  # noqa: E501
    monkeypatch.setattr(fake_jinni, "print_active", lambda: (True, "printing"))
    assert jinni_client.blocked_actions() == fake_jinni.blocked_actions()
    assert jinni_client.blocked_actions()


async def test_subscribe_blocked_actions_streams_in_process(fake_jinni: FakeKlipperJinni) -> None:
    frames = [blocked async for blocked in jinni_client.subscribe_blocked_actions()]
    assert frames == [frozenset()]


def test_capabilities_report_folds_in_interface_extras(fake_jinni: FakeKlipperJinni) -> None:
    report = jinni_client.capabilities_report()
    assert report["adapter"] == fake_jinni.id
    assert "interface_extras" in report


def test_health_on_a_generic_target_reports_no_services(monkeypatch: pytest.MonkeyPatch) -> None:
    # The seam does not narrow to a printer tier: a generic box answers health() too, declaring no
    # critical services (so it is vacuously healthy).
    fake = FakeGenericJinni()
    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", lambda: fake)
    report = jinni_client.health()
    assert report.services == {}
    assert report.healthy is True
