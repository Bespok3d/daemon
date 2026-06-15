"""The jinni classifies its own service commands (ADR-0037 proof slice).

This is where the daemon's old `service_actions` predicates moved: the jinni that produced a restart
command judges what it does, so the daemon never matches a command string. A bare klipper tier knows
Klipper/Moonraker (the domain); the device tier adds its own markers and display tokens.
"""
from jinni import KlipperPrinterJinni
from jinni.base import Jinni
from jinni.contracts import (
    RESTART_DISPLAY,
    RESTART_KLIPPER,
    CommandEffect,
)


class _U1LikeJinni(KlipperPrinterJinni):
    def deferred_service_markers(self) -> tuple[str, ...]:
        return ("init.d", "nginx")

    def display_service_tokens(self) -> tuple[str, ...]:
        return ("lmdctl",)


def _effect(jinni: Jinni, command: str) -> CommandEffect:
    return jinni.classify_commands([command])[0]


def test_klipper_restart_is_a_core_service_action() -> None:
    effect = _effect(_U1LikeJinni(), "/etc/init.d/S60klipper restart")
    assert effect.restarts_klipper
    assert effect.blocking_token == RESTART_KLIPPER
    assert effect.deferrable
    assert not effect.restarts_moonraker


def test_moonraker_restart_is_detected_across_init_systems() -> None:
    assert _effect(_U1LikeJinni(), "/etc/init.d/S61moonraker restart").restarts_moonraker
    assert _effect(_U1LikeJinni(), "systemctl reload moonraker").restarts_moonraker
    assert not _effect(_U1LikeJinni(), "/etc/init.d/S60klipper restart").restarts_moonraker


def test_display_restart_interrupts_a_print_without_being_a_core_service() -> None:
    effect = _effect(_U1LikeJinni(), "$BESPOK3D/etc/init.d/lmdctl restart")
    assert effect.blocking_token == RESTART_DISPLAY
    assert effect.deferrable
    assert not effect.restarts_klipper
    assert not effect.restarts_moonraker


def test_a_plugin_service_bounce_is_deferred_but_does_not_interrupt_a_print() -> None:
    for command in (
        "/b/etc/init.d/autostart/s65camera-hw restart",
        "sh /b/files/etc/init.d/s90mainsail start 8080",
        "/usr/sbin/nginx -s reload",
    ):
        effect = _effect(_U1LikeJinni(), command)
        assert effect.deferrable
        assert effect.blocking_token is None


def test_config_generation_commands_run_inline() -> None:
    for command in (
        "sed 's/X/Y/g' > /b/moonraker/spoolman.cfg",
        "chown lava:lava /b/moonraker/spoolman.cfg",
        "echo lmdctl is great",
    ):
        effect = _effect(_U1LikeJinni(), command)
        assert not effect.deferrable
        assert effect.blocking_token is None


def test_a_bare_klipper_tier_defers_core_services_but_not_device_only_commands() -> None:
    bare = KlipperPrinterJinni()
    assert _effect(bare, "systemctl restart klipper").deferrable
    # no device markers, so an init.d plugin bounce is not recognised as deferrable here
    assert not _effect(bare, "/b/etc/init.d/autostart/s65camera-hw restart").deferrable
    # no display tokens, so an lmd restart does not read as print-interrupting on the bare tier
    assert _effect(bare, "$BESPOK3D/etc/init.d/lmdctl restart").blocking_token is None


def test_a_generic_box_has_no_service_actions() -> None:
    effects = Jinni().classify_commands(["systemctl restart klipper", "/usr/sbin/nginx -s reload"])
    assert all(effect == CommandEffect(False, False, False, None) for effect in effects)
