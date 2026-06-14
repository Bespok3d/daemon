from core import service_actions


def test_restarts_lmd_detection() -> None:
    assert service_actions.restarts_lmd("/userdata/bespok3d/etc/init.d/lmdctl restart")
    assert service_actions.restarts_lmd("/userdata/bespok3d/etc/init.d/lmdctl start")
    assert not service_actions.restarts_lmd("/etc/init.d/S60klipper restart")
    assert not service_actions.restarts_lmd("echo lmdctl is great")


def test_restarts_moonraker_detection() -> None:
    assert service_actions.restarts_moonraker("/etc/init.d/S61moonraker restart")
    assert service_actions.restarts_moonraker("/etc/init.d/S61moonraker start")
    assert service_actions.restarts_moonraker("systemctl reload moonraker")
    assert not service_actions.restarts_moonraker("/etc/init.d/S60klipper restart")
    assert not service_actions.restarts_moonraker("echo moonraker is great")


def test_lmd_restart_is_deferred_but_not_a_core_service() -> None:
    cmd = "/userdata/bespok3d/etc/init.d/lmdctl restart"
    assert service_actions.is_service_action(cmd)
    assert not service_actions.restarts_klipper(cmd)
    assert not service_actions.restarts_moonraker(cmd)


def test_service_action_detection() -> None:
    assert service_actions.restarts_klipper("/etc/init.d/S60klipper restart")
    assert service_actions.restarts_moonraker("/etc/init.d/S61moonraker restart")
    # every init-script restart / start and nginx reload is deferred to the end
    assert service_actions.is_service_action("/etc/init.d/S61moonraker restart")
    assert service_actions.is_service_action("/etc/init.d/S60klipper restart")
    assert service_actions.is_service_action("/b/etc/init.d/autostart/s65camera-hw restart")
    assert service_actions.is_service_action("sh /b/files/etc/init.d/s90mainsail start 8080")
    assert service_actions.is_service_action("/usr/sbin/nginx -s reload")
    # config-generation commands run inline, never deferred
    assert not service_actions.is_service_action("sed 's/X/Y/g' > /b/moonraker/spoolman.cfg")
    assert not service_actions.is_service_action("chown lava:lava /b/moonraker/spoolman.cfg")
    assert not service_actions.is_service_action("sed -i '/^\\[rfid\\]/d' /b/printer.cfg")
