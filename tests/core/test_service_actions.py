from core import service_actions
from jinni.contracts import ServiceActionVocabulary

# The U1's vocabulary: the display control script + the init-script / web-server markers.
_VOCAB = ServiceActionVocabulary(display_services=("lmdctl",), service_markers=("init.d", "nginx"))


def test_restarts_lmd_detection() -> None:
    assert service_actions.restarts_lmd("/userdata/bespok3d/etc/init.d/lmdctl restart", _VOCAB)
    assert service_actions.restarts_lmd("/userdata/bespok3d/etc/init.d/lmdctl start", _VOCAB)
    assert not service_actions.restarts_lmd("/etc/init.d/S60klipper restart", _VOCAB)
    assert not service_actions.restarts_lmd("echo lmdctl is great", _VOCAB)


def test_restarts_moonraker_detection() -> None:
    assert service_actions.restarts_moonraker("/etc/init.d/S61moonraker restart")
    assert service_actions.restarts_moonraker("/etc/init.d/S61moonraker start")
    assert service_actions.restarts_moonraker("systemctl reload moonraker")
    assert not service_actions.restarts_moonraker("/etc/init.d/S60klipper restart")
    assert not service_actions.restarts_moonraker("echo moonraker is great")


def test_lmd_restart_is_deferred_but_not_a_core_service() -> None:
    cmd = "/userdata/bespok3d/etc/init.d/lmdctl restart"
    assert service_actions.is_service_action(cmd, _VOCAB)
    assert not service_actions.restarts_klipper(cmd)
    assert not service_actions.restarts_moonraker(cmd)


def _deferred(expanded_cmd: str) -> bool:
    return service_actions.is_service_action(expanded_cmd, _VOCAB)


def test_service_action_detection() -> None:
    assert service_actions.restarts_klipper("/etc/init.d/S60klipper restart")
    assert service_actions.restarts_moonraker("/etc/init.d/S61moonraker restart")
    # every init-script restart / start and nginx reload is deferred to the end
    assert _deferred("/etc/init.d/S61moonraker restart")
    assert _deferred("/etc/init.d/S60klipper restart")
    assert _deferred("/b/etc/init.d/autostart/s65camera-hw restart")
    assert _deferred("sh /b/files/etc/init.d/s90mainsail start 8080")
    assert _deferred("/usr/sbin/nginx -s reload")
    # config-generation commands run inline, never deferred
    assert not _deferred("sed 's/X/Y/g' > /b/moonraker/spoolman.cfg")
    assert not _deferred("chown lava:lava /b/moonraker/spoolman.cfg")
    assert not _deferred("sed -i '/^\\[rfid\\]/d' /b/printer.cfg")


def test_an_empty_vocabulary_detects_no_device_service_action() -> None:
    empty = ServiceActionVocabulary()
    assert not service_actions.restarts_lmd("/etc/init.d/lmdctl restart", empty)
    assert not service_actions.is_service_action("/usr/sbin/nginx -s reload", empty)
