import json
from pathlib import Path

import pytest

from core import packages
from core.packages import print_guard

MP = pytest.MonkeyPatch


def test_orchestrator_reexports_the_guards() -> None:
    assert packages.guard_no_print is print_guard.guard_no_print
    assert packages.guard_no_print_for_removal is print_guard.guard_no_print_for_removal


def test_print_active_reads_klipper_api_socket(monkeypatch: MP) -> None:
    # The guard must see a print in progress even under force_logins, via Klipper's own socket.
    monkeypatch.setattr(print_guard, "klippy_socket_path", lambda: "/tmp/klippy.sock")
    monkeypatch.setattr(print_guard, "query_print_state", lambda _path: "printing")
    assert print_guard._print_active() == (True, "printing")


def test_print_active_falls_back_to_moonraker_without_a_socket(monkeypatch: MP) -> None:
    monkeypatch.setattr(print_guard, "klippy_socket_path", lambda: "")
    monkeypatch.setattr(print_guard, "_print_state_via_moonraker", lambda: "paused")
    assert print_guard._print_active() == (True, "paused")


def test_print_active_idle_when_socket_unreachable_and_moonraker_silent(monkeypatch: MP) -> None:
    monkeypatch.setattr(print_guard, "klippy_socket_path", lambda: "/tmp/klippy.sock")
    monkeypatch.setattr(print_guard, "query_print_state", lambda _path: None)
    monkeypatch.setattr(print_guard, "_print_state_via_moonraker", lambda: "")
    assert print_guard._print_active() == (False, "")


def test_guard_blocks_install_that_restarts_during_print(monkeypatch: MP) -> None:
    monkeypatch.setattr(print_guard, "_print_active", lambda: (True, "printing"))
    manifest = {"name": "tmc-low-current", "install": {"start": ["/etc/init.d/S60klipper restart"]}}
    with pytest.raises(ValueError, match="print is printing"):
        print_guard.guard_no_print_during_restart(manifest)


def test_guard_allows_install_when_printer_idle(monkeypatch: MP) -> None:
    monkeypatch.setattr(print_guard, "_print_active", lambda: (False, "standby"))
    manifest = {"name": "tmc-low-current", "install": {"start": ["/etc/init.d/S60klipper restart"]}}
    print_guard.guard_no_print_during_restart(manifest)


def test_guard_ignores_install_that_does_not_restart_services(monkeypatch: MP) -> None:
    def fail_if_called() -> tuple[bool, str]:
        raise AssertionError("print state must not be checked when no restart happens")

    monkeypatch.setattr(print_guard, "_print_active", fail_if_called)
    print_guard.guard_no_print_during_restart({"name": "x", "install": {"start": []}})


def test_guard_blocks_lmd_restart_hook_during_print(monkeypatch: MP) -> None:
    monkeypatch.setattr(print_guard, "_print_active", lambda: (True, "printing"))
    manifest = {"name": "x", "install": {"restart": ["lmd"]}}
    with pytest.raises(ValueError, match="print is printing"):
        print_guard.guard_no_print_during_restart(manifest)


def test_guard_blocks_display_plugin_via_teardown_stop_during_print(monkeypatch: MP) -> None:
    monkeypatch.setattr(print_guard, "_print_active", lambda: (True, "printing"))
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
    with pytest.raises(ValueError, match="print is printing"):
        print_guard.guard_no_print_during_restart(manifest)


def test_guard_blocks_camera_install_when_paused(monkeypatch: MP) -> None:
    # a paused print counts as active: bouncing the camera/display would still disrupt the user.
    assert "paused" in print_guard._PRINTING_STATES
    monkeypatch.setattr(print_guard, "_print_active", lambda: (True, "paused"))
    manifest = {
        "name": "camera-hw-accel",
        "install": {"start": ["$BESPOK3D/etc/init.d/autostart/s65camera-hw restart"]},
        "stop": ["$BESPOK3D/etc/init.d/lmdctl restart"],
    }
    with pytest.raises(ValueError, match="print is paused"):
        print_guard.guard_no_print_during_restart(manifest)


def test_guard_no_print_for_removal_blocks_display_plugin_during_print(
    tmp_path: Path, monkeypatch: MP
) -> None:
    # removing the camera bounces lmd via its teardown stop, so it is locked while printing too.
    monkeypatch.setattr(print_guard, "_print_active", lambda: (True, "printing"))
    cam = tmp_path / "camera-hw-accel"
    cam.mkdir()
    (cam / "manifest.json").write_text(json.dumps({
        "name": "camera-hw-accel",
        "install": {"start": []},
        "stop": ["$BESPOK3D/etc/init.d/lmdctl restart"],
    }))
    with pytest.raises(ValueError, match="Cannot remove camera-hw-accel while a print is printing"):
        print_guard.guard_no_print_for_removal(tmp_path, ["camera-hw-accel"])
