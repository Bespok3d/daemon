import pytest

from core import autostart, intent


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


def test_kernel_module_placement_symlinks_into_the_modules_dir() -> None:
    ops = intent.normalize_install(
        {"place": [{"class": "kernel-module", "name": "tun.ko", "src": "files/modules/tun.ko"}]}
    )
    assert ops["symlinks"] == [
        {"from": "files/modules/tun.ko", "to": "$BESPOK3D/lib/modules/tun.ko"}
    ]


def test_kmodule_wires_an_s05_loader_that_sorts_before_the_s65_services() -> None:
    ops = intent.normalize_install({
        "place": [{"class": "kernel-module", "name": "tun.ko", "src": "files/modules/tun.ko"}],
        "service": [{"name": "zerotier", "command": "/x", "autostart": True}],
        "kmodule": [{"name": "tun", "module": "tun.ko", "autoload": True}],
    })
    module_link = {"from": "etc/init.d/s05tun", "to": "$BESPOK3D/etc/init.d/autostart/s05tun"}
    service_link = {
        "from": "etc/init.d/s65zerotier", "to": "$BESPOK3D/etc/init.d/autostart/s65zerotier"
    }
    assert module_link in ops["symlinks"]
    assert service_link in ops["symlinks"]
    # ANY s05 module sorts before ANY s65 service, so the boot runner (`ls | sort`) loads the module
    # before the service that needs it, even when the module name sorts after the service name.
    module_script = autostart.kmodule_script_name({"name": "zzz"})
    service_script = autostart.service_script_name({"name": "aaa"})
    assert module_script < service_script


def test_kmodule_load_runs_immediately_not_through_the_deferred_restart_batch() -> None:
    ops = intent.normalize_install({
        "place": [{"class": "kernel-module", "name": "tun.ko", "src": "files/modules/tun.ko"}],
        "kmodule": [{"name": "tun", "module": "tun.ko", "autoload": True}],
    })
    autostart = "$BESPOK3D/etc/init.d/autostart/s05tun"
    # `restart` (unload/load), so an update that ships a changed .ko reloads it in place
    assert ops["module_loads"] == [f"{autostart} restart"]
    # a module load never batches with the deferred core-service restarts
    assert f"{autostart} restart" not in ops["start"]
    assert ops["stops"] == [f"{autostart} stop"]


def test_kmodule_without_autoload_still_wires_and_unloads_but_does_not_load() -> None:
    ops = intent.normalize_install({
        "place": [{"class": "kernel-module", "name": "tun.ko", "src": "files/modules/tun.ko"}],
        "kmodule": [{"name": "tun", "module": "tun.ko"}],
    })
    assert ops["module_loads"] == []
    assert ops["stops"] == ["$BESPOK3D/etc/init.d/autostart/s05tun stop"]
    assert ops["symlinks"] == [
        {"from": "files/modules/tun.ko", "to": "$BESPOK3D/lib/modules/tun.ko"},
        {"from": "etc/init.d/s05tun", "to": "$BESPOK3D/etc/init.d/autostart/s05tun"},
    ]


def test_variant_place_with_a_falsy_name_is_refused_not_a_keyerror() -> None:
    # A present-but-null name is as unstable as a missing one, and a variant entry has no top-level
    # src to fall back on: reject it with the clean ValueError, never a KeyError.
    with pytest.raises(ValueError, match="must declare an explicit name"):
        intent.normalize_install(
            {
                "place": [{
                    "class": "kernel-module", "name": None,
                    "variants": [{"when": {"kernel_release": "6.1.99"}, "src": "files/tun.ko"}],
                }],
                "kmodule": [{"name": "tun", "module": "tun.ko"}],
            },
            {"kernel_release": "6.1.99"},
        )


def test_kmodule_naming_an_unplaced_module_is_refused() -> None:
    # A typo where install.kmodule.module does not match any placed .ko would fail insmod on the
    # device (a safe deactivate). Fail loud at install instead.
    with pytest.raises(ValueError, match="no place entry ships"):
        intent.normalize_install({"kmodule": [{"name": "tun", "module": "tun.ko"}]})


def test_kmodule_matches_a_variant_place_by_its_stable_name() -> None:
    # The .ko place carries kernel variants but a stable `name` (the variant-name guard); the
    # kmodule names that stable target, so the check holds no matter which kernel a printer picks.
    manifest = {
        "place": [{
            "class": "kernel-module", "name": "tun.ko",
            "variants": [
                {"when": {"kernel_release": "6.1.99"}, "src": "files/modules/tun-6.1.99.ko"}
            ],
        }],
        "kmodule": [{"name": "tun", "module": "tun.ko", "autoload": True}],
    }
    ops = intent.normalize_install(manifest, {"kernel_release": "6.1.99"})
    assert {
        "from": "files/modules/tun-6.1.99.ko", "to": "$BESPOK3D/lib/modules/tun.ko"
    } in ops["symlinks"]


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


_U1_FACTS = {
    "adapter": "snapmaker-u1", "arch": "aarch64", "firmware_version": "1.4.1",
    "board_class": "standard",
}


def test_variant_selection_picks_matching_arch() -> None:
    ops = intent.normalize_install(
        {"place": [{
            "class": "system-bin",
            "name": "zerotier-one",
            "variants": [
                {"when": {"arch": "x86_64"}, "src": "files/bin/zerotier-one-amd64"},
                {"when": {"arch": "aarch64"}, "src": "files/bin/zerotier-one-arm64"},
            ],
        }]},
        _U1_FACTS,
    )
    assert ops["symlinks"] == [
        {"from": "files/bin/zerotier-one-arm64", "to": "$BESPOK3D/bin/zerotier-one"}
    ]


def test_no_matching_variant_is_skipped() -> None:
    ops = intent.normalize_install(
        {"place": [{
            "class": "system-bin",
            "name": "zerotier-one",
            "variants": [{"when": {"arch": "x86_64"}, "src": "files/bin/zerotier-one-amd64"}],
        }]},
        _U1_FACTS,
    )
    assert ops["symlinks"] == []
    assert ops["templates"] == []


def test_instrument_variant_selects_the_matching_diff() -> None:
    old_firmware = {**_U1_FACTS, "firmware_version": "1.4.0.38"}
    ops = intent.normalize_install(
        {"instrument": [{
            "class": "klipper-source",
            "name": "extras/fm175xx_reader.py",
            "variants": [
                {"when": {"fw_max": "1.4.0.244"}, "diff": "files/p/ppins.patch"},
                {"diff": "files/p/gpiod.patch"},
            ],
        }]},
        old_firmware,
    )
    assert ops["patches"] == [
        {"file": "$KLIPPER_SRC/extras/fm175xx_reader.py", "patch": "files/p/ppins.patch"}
    ]


def test_render_variant_emits_template_then_symlink_of_the_chosen_source() -> None:
    ops = intent.normalize_install(
        {"place": [{
            "class": "moonraker-config",
            "name": "vpn.cfg",
            "render": True,
            "variants": [{"when": {"board_class": "standard"}, "src": "files/cfg/vpn.cfg.tmpl"}],
        }]},
        _U1_FACTS,
    )
    assert ops["templates"] == [
        {"from": "files/cfg/vpn.cfg.tmpl", "to": "files/cfg/vpn.cfg"}
    ]
    assert ops["symlinks"] == [
        {"from": "files/cfg/vpn.cfg", "to": "$BESPOK3D_MOONRAKER/vpn.cfg"}
    ]


def test_place_variant_without_an_explicit_name_is_refused() -> None:
    with pytest.raises(ValueError, match="must declare an explicit name"):
        intent.normalize_install(
            {"place": [{
                "class": "system-bin",
                "variants": [{"when": {"arch": "aarch64"}, "src": "files/bin/zt-arm64"}],
            }]},
            _U1_FACTS,
        )


def test_entry_without_variants_resolves_normally_despite_facts() -> None:
    ops = intent.normalize_install(
        {"place": [{"class": "klipper-config", "src": "files/cfg/klipper/cpu-temp.cfg"}]},
        _U1_FACTS,
    )
    assert ops["symlinks"] == [
        {"from": "files/cfg/klipper/cpu-temp.cfg", "to": "$BESPOK3D_KLIPPER/cpu-temp.cfg"}
    ]
