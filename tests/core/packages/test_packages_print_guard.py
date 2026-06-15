"""Print-guard behavior: which ops the guard checks, and that it refuses with blocked-action TOKENS
(ADR-0037) while a print runs. The live blocked-set itself is the jinni's, tested in
tests/jinni/test_print_active.py; here the guard decides which ops need the check and raises a
structured `BlockedActionError` carrying the offending tokens, never an English sentence.
"""
import json
from pathlib import Path

import pytest

from core import packages
from core.packages import print_guard
from core.packages.errors import BlockedActionError
from jinni.base import Jinni
from jinni.contracts import RESTART_DISPLAY, RESTART_KLIPPER

MP = pytest.MonkeyPatch


def test_orchestrator_reexports_the_guards() -> None:
    assert packages.guard_no_print is print_guard.guard_no_print


def test_guard_blocks_install_that_restarts_during_print(
    monkeypatch: MP, device_jinni: Jinni,
) -> None:
    monkeypatch.setattr(device_jinni, "print_active", lambda: (True, "printing"))
    manifest = {"name": "tmc-low-current", "install": {"start": ["/etc/init.d/S60klipper restart"]}}
    with pytest.raises(BlockedActionError) as raised:
        print_guard.guard_no_print_during_restart(manifest)
    assert RESTART_KLIPPER in raised.value.blocked


def test_guard_allows_install_when_printer_idle(monkeypatch: MP, device_jinni: Jinni) -> None:
    monkeypatch.setattr(device_jinni, "print_active", lambda: (False, "standby"))
    manifest = {"name": "tmc-low-current", "install": {"start": ["/etc/init.d/S60klipper restart"]}}
    print_guard.guard_no_print_during_restart(manifest)


def test_guard_ignores_install_that_does_not_restart_services(
    monkeypatch: MP, device_jinni: Jinni,
) -> None:
    def fail_if_called() -> object:
        raise AssertionError("the blocked set must not be read when no restart happens")

    monkeypatch.setattr(device_jinni, "blocked_actions", fail_if_called)
    print_guard.guard_no_print_during_restart({"name": "x", "install": {"start": []}})


def test_guard_blocks_lmd_restart_hook_during_print(monkeypatch: MP, device_jinni: Jinni) -> None:
    monkeypatch.setattr(device_jinni, "print_active", lambda: (True, "printing"))
    manifest = {"name": "x", "install": {"restart": ["lmd"]}}
    with pytest.raises(BlockedActionError) as raised:
        print_guard.guard_no_print_during_restart(manifest)
    assert RESTART_DISPLAY in raised.value.blocked


def test_guard_blocks_display_plugin_via_teardown_stop_during_print(
    monkeypatch: MP, device_jinni: Jinni,
) -> None:
    monkeypatch.setattr(device_jinni, "print_active", lambda: (True, "printing"))
    # camera-hw-accel restarts lmd inside its own init script (no literal "lmd" in start); its
    # teardown `stop` declaring lmdctl marks it as display-touching.
    manifest = {
        "name": "camera-hw-accel",
        "install": {"start": ["$BESPOK3D/etc/init.d/autostart/s65camera-hw restart"]},
        "stop": [
            "$BESPOK3D/etc/init.d/autostart/s65camera-hw stop",
            "$BESPOK3D/etc/init.d/lmdctl restart",
        ],
    }
    with pytest.raises(BlockedActionError) as raised:
        print_guard.guard_no_print_during_restart(manifest)
    assert RESTART_DISPLAY in raised.value.blocked


def test_guard_blocks_camera_install_when_paused(monkeypatch: MP, device_jinni: Jinni) -> None:
    # a paused print counts as active: bouncing the camera/display would still disrupt the user.
    assert device_jinni.is_active_print_state("paused") is True
    monkeypatch.setattr(device_jinni, "print_active", lambda: (True, "paused"))
    manifest = {
        "name": "camera-hw-accel",
        "install": {"start": ["$BESPOK3D/etc/init.d/autostart/s65camera-hw restart"]},
        "stop": ["$BESPOK3D/etc/init.d/lmdctl restart"],
    }
    with pytest.raises(BlockedActionError):
        print_guard.guard_no_print_during_restart(manifest)


def test_guard_no_print_for_removal_blocks_display_plugin_during_print(
    tmp_path: Path, monkeypatch: MP, device_jinni: Jinni,
) -> None:
    # removing the camera bounces lmd via its teardown stop, so it is locked while printing too.
    monkeypatch.setattr(device_jinni, "print_active", lambda: (True, "printing"))
    cam = tmp_path / "camera-hw-accel"
    cam.mkdir()
    (cam / "manifest.json").write_text(json.dumps({
        "name": "camera-hw-accel",
        "install": {"start": []},
        "stop": ["$BESPOK3D/etc/init.d/lmdctl restart"],
    }))
    with pytest.raises(BlockedActionError) as raised:
        print_guard.guard_no_print_for_removal(tmp_path, ["camera-hw-accel"])
    assert RESTART_DISPLAY in raised.value.blocked
