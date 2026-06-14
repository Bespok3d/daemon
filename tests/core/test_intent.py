import pytest

from core import intent


def test_placement_becomes_symlink_into_class_destination() -> None:
    ops = intent.normalize_install(
        {"place": [{"class": "klipper-config", "src": "files/cfg/klipper/cpu-temp.cfg"}]}
    )
    assert ops["symlinks"] == [
        {"from": "files/cfg/klipper/cpu-temp.cfg", "to": "$BESPOK3D_KLIPPER/cpu-temp.cfg"}
    ]
    assert ops["templates"] == []


def test_system_bin_placement_symlinks_into_bespok3d_bin() -> None:
    ops = intent.normalize_install(
        {"place": [{"class": "system-bin", "src": "files/bin/curl"}]}
    )
    assert ops["symlinks"] == [{"from": "files/bin/curl", "to": "$BESPOK3D/bin/curl"}]


def test_placement_name_overrides_basename() -> None:
    ops = intent.normalize_install(
        {"place": [{"class": "klipper-extra", "src": "files/k/helper.py", "name": "sh.py"}]}
    )
    assert ops["symlinks"] == [{"from": "files/k/helper.py", "to": "$KLIPPER_EXTRAS/sh.py"}]


def test_render_placement_emits_template_then_symlink_of_rendered_file() -> None:
    ops = intent.normalize_install(
        {
            "place": [
                {
                    "class": "moonraker-config",
                    "src": "files/cfg/moonraker/spoolman.cfg.tmpl",
                    "name": "spoolman.cfg",
                    "render": True,
                }
            ]
        }
    )
    assert ops["templates"] == [
        {"from": "files/cfg/moonraker/spoolman.cfg.tmpl", "to": "files/cfg/moonraker/spoolman.cfg"}
    ]
    assert ops["symlinks"] == [
        {"from": "files/cfg/moonraker/spoolman.cfg", "to": "$BESPOK3D_MOONRAKER/spoolman.cfg"}
    ]


def test_instrument_becomes_patch_against_klipper_source() -> None:
    ops = intent.normalize_install(
        {
            "instrument": [
                {"class": "klipper-source", "name": "toolhead.py", "diff": "files/p/02.patch"},
                {
                    "class": "klipper-source",
                    "name": "extras/fm175xx_reader.py",
                    "diff": "files/p/fm.patch",
                },
            ]
        }
    )
    assert ops["patches"] == [
        {"file": "$KLIPPER_SRC/toolhead.py", "patch": "files/p/02.patch"},
        {"file": "$KLIPPER_SRC/extras/fm175xx_reader.py", "patch": "files/p/fm.patch"},
    ]


def test_unsupported_instrument_class_is_refused() -> None:
    with pytest.raises(ValueError, match="unsupported instrument class"):
        intent.normalize_install(
            {"instrument": [{"class": "kernel", "name": "x", "diff": "files/x.patch"}]}
        )


def test_restart_hooks_become_start_commands() -> None:
    ops = intent.normalize_install({"restart": ["klipper", "moonraker", "web"]})
    assert ops["start"] == [
        "/etc/init.d/S60klipper restart",
        "/etc/init.d/S61moonraker restart",
        "/usr/sbin/nginx -s reload",
    ]


def test_lmd_restart_hook_maps_to_lmdctl() -> None:
    ops = intent.normalize_install({"restart": ["lmd"]})
    assert ops["start"] == ["$BESPOK3D/etc/init.d/lmdctl restart"]


def test_web_location_placement_targets_nginx_locations() -> None:
    ops = intent.normalize_install(
        {"place": [{"class": "web-location", "src": "files/nginx/s.conf"}]}
    )
    assert ops["symlinks"] == [
        {"from": "files/nginx/s.conf", "to": "$BESPOK3D/etc/nginx/locations/s.conf"}
    ]


def test_autostart_service_wires_symlink_start_and_stop() -> None:
    ops = intent.normalize_install(
        {"service": [{"name": "remote-screen", "command": "/usr/bin/python3", "autostart": True}]}
    )
    autostart = "$BESPOK3D/etc/init.d/autostart/s65remote-screen"
    assert ops["symlinks"] == [{"from": "etc/init.d/s65remote-screen", "to": autostart}]
    assert ops["start"] == [f"{autostart} restart"]
    assert ops["stops"] == [f"{autostart} stop"]


def test_non_autostart_service_still_stops_but_does_not_start() -> None:
    ops = intent.normalize_install(
        {"service": [{"name": "worker", "command": "/usr/bin/worker"}]}
    )
    assert ops["start"] == []
    assert ops["stops"] == ["$BESPOK3D/etc/init.d/autostart/s65worker stop"]


def test_data_becomes_var_lib_dir() -> None:
    ops = intent.normalize_install({"data": ["spoolman"]})
    assert ops["dirs"] == ["$BESPOK3D/var/lib/spoolman"]


def test_legacy_keys_pass_through_unchanged() -> None:
    legacy = {
        "symlinks": [{"from": "a", "to": "$X/a"}],
        "patches": [{"file": "$X/b", "patch": "files/b.patch"}],
        "start": ["/etc/init.d/S60klipper restart"],
    }
    ops = intent.normalize_install(legacy)
    assert ops["symlinks"] == legacy["symlinks"]
    assert ops["patches"] == legacy["patches"]
    assert ops["start"] == legacy["start"]


def test_unsupported_class_is_refused() -> None:
    with pytest.raises(ValueError, match="unsupported destination class"):
        intent.normalize_install({"place": [{"class": "mystery", "src": "files/x"}]})


def test_unsupported_restart_hook_is_refused() -> None:
    with pytest.raises(ValueError, match="unsupported restart hook"):
        intent.normalize_install({"restart": ["database"]})


def test_restarts_lmd_detection() -> None:
    assert intent.restarts_lmd("/userdata/bespok3d/etc/init.d/lmdctl restart")
    assert intent.restarts_lmd("/userdata/bespok3d/etc/init.d/lmdctl start")
    assert not intent.restarts_lmd("/etc/init.d/S60klipper restart")
    assert not intent.restarts_lmd("echo lmdctl is great")


def test_restarts_moonraker_detection() -> None:
    assert intent.restarts_moonraker("/etc/init.d/S61moonraker restart")
    assert intent.restarts_moonraker("/etc/init.d/S61moonraker start")
    assert intent.restarts_moonraker("systemctl reload moonraker")
    assert not intent.restarts_moonraker("/etc/init.d/S60klipper restart")
    assert not intent.restarts_moonraker("echo moonraker is great")


def test_lmd_restart_is_deferred_but_not_a_core_service() -> None:
    cmd = "/userdata/bespok3d/etc/init.d/lmdctl restart"
    assert intent.is_service_action(cmd)
    assert not intent.restarts_klipper(cmd)
    assert not intent.restarts_moonraker(cmd)


def test_service_action_detection() -> None:
    assert intent.restarts_klipper("/etc/init.d/S60klipper restart")
    assert intent.restarts_moonraker("/etc/init.d/S61moonraker restart")
    # every init-script restart / start and nginx reload is deferred to the end
    assert intent.is_service_action("/etc/init.d/S61moonraker restart")
    assert intent.is_service_action("/etc/init.d/S60klipper restart")
    assert intent.is_service_action("/b/etc/init.d/autostart/s65camera-hw restart")
    assert intent.is_service_action("sh /b/files/etc/init.d/s90mainsail start 8080")
    assert intent.is_service_action("/usr/sbin/nginx -s reload")
    # config-generation commands run inline, never deferred
    assert not intent.is_service_action("sed 's/X/Y/g' > /b/moonraker/spoolman.cfg")
    assert not intent.is_service_action("chown lava:lava /b/moonraker/spoolman.cfg")
    assert not intent.is_service_action("sed -i '/^\\[rfid\\]/d' /b/printer.cfg")
