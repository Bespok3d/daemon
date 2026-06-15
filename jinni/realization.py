"""The realization facet of the jinni: turn an install intent into a concrete target or command.

When the daemon places a file, instruments a source, restarts a service, generates a service script,
seeds a startup control script, or asks what a generated command does to the device's services, it
does not hardcode where or how; it asks the jinni. The base tier owns the bespok3d-layout placement
classes and otherwise realizes nothing (a generic box has no klipper config dir, no restart command,
no service to restart); the klipper tier and the device jinni add their classes, commands, and
service tokens, deferring to `super()` for the base ones.
"""
import re
from collections.abc import Coroutine
from typing import Any

from .contracts import (
    RESTART_DISPLAY,
    RESTART_KLIPPER,
    RESTART_MOONRAKER,
    CommandEffect,
    ControlScript,
)

# A restart/start/reload verb against a service. The generic verb is the only part of command
# classification that is device-agnostic; the service names and device tokens come from the tier.
_SERVICE_ACTION_RE = re.compile(r"\b(?:restart|start|reload)\b")

_INERT_COMMAND = CommandEffect(
    deferrable=False, restarts_klipper=False, restarts_moonraker=False, blocking_token=None,
)


def _blocking_token(restarts_klipper: bool, restarts_moonraker: bool, restarts_display: bool) -> str | None:  # noqa: E501
    if restarts_klipper:
        return RESTART_KLIPPER
    if restarts_moonraker:
        return RESTART_MOONRAKER
    if restarts_display:
        return RESTART_DISPLAY
    return None


def _classify_one(command: str, markers: tuple[str, ...], display_tokens: tuple[str, ...]) -> CommandEffect:  # noqa: E501
    if not _SERVICE_ACTION_RE.search(command):
        return _INERT_COMMAND
    restarts_klipper = "klipper" in command
    restarts_moonraker = "moonraker" in command
    restarts_display = any(token in command for token in display_tokens)
    token = _blocking_token(restarts_klipper, restarts_moonraker, restarts_display)
    return CommandEffect(
        deferrable=token is not None or any(marker in command for marker in markers),
        restarts_klipper=restarts_klipper,
        restarts_moonraker=restarts_moonraker,
        blocking_token=token,
    )

# Placement classes the bespok3d layout owns directly (over the daemon's own $BESPOK3D tree). They
# resolve to a $VAR-templated path the executor expands; the value names no concrete device. Klipper
# placement classes live on the klipper tier (jinni/klipper.py).
_BESPOK3D_PLACEMENTS = {
    "system-bin": "$BESPOK3D/bin/{name}",
    "web-location": "$BESPOK3D/etc/nginx/locations/{name}",
}


class Realization:
    def placement_destination(self, destination_class: str, name: str) -> str:
        """The $VAR-templated path a placed file of `destination_class` lands at. The base tier owns
        the bespok3d-layout classes; a printer tier adds its own and defers to super() for these."""
        template = _BESPOK3D_PLACEMENTS.get(destination_class)
        if template is None:
            raise ValueError(f"unsupported destination class: {destination_class}")
        return template.format(name=name)

    def instrument_destination(self, instrument_class: str, name: str) -> str:
        """The $VAR-templated path an instrumentation diff patches. The base tier instruments
        nothing; a printer tier adds its source classes and defers to super() for the unknown."""
        raise ValueError(f"unsupported instrument class: {instrument_class}")

    def restart_command(self, hook: str) -> str | None:
        """The shell command that restarts the core service named by `hook` (klipper, moonraker,
        web, lmd), or None when the device has no such service. The commands are genuine device
        facts, so the base tier knows none; a device jinni supplies them."""
        return None

    def classify_commands(self, commands: list[str]) -> list[CommandEffect]:
        """How each generated start command acts on the device's services. A generic box has no
        services, so nothing is a service action; the klipper tier judges the real ones."""
        return [_INERT_COMMAND for _ in commands]

    def render_service_script(self, service: dict, paths: dict[str, str]) -> str:
        raise NotImplementedError("managed-service")

    def startup_control_scripts(self, paths: dict[str, str]) -> list[ControlScript]:
        """Control scripts the daemon writes into the persistent bespok3d tree on startup (e.g. a
        display control script). The base tier declares none; a device jinni returns its own."""
        return []

    def background_tasks(self) -> list[Coroutine[Any, Any, None]]:
        return []


# Placement and instrument classes a klipper printer adds, resolving to $VAR-templated paths over
# the klipper layout contract (KLIPPER_PATH_KEYS). The executor expands the variables from the
# device jinni's paths; the values name no concrete device.
_KLIPPER_PLACEMENTS = {
    "klipper-config": "$BESPOK3D_KLIPPER/{name}",
    "moonraker-config": "$BESPOK3D_MOONRAKER/{name}",
    "klipper-extra": "$KLIPPER_EXTRAS/{name}",
    "moonraker-component": "$MOONRAKER_COMPONENTS/{name}",
}
_KLIPPER_INSTRUMENTS = {
    "klipper-source": "$KLIPPER_SRC/{name}",
}


class KlipperRealization(Realization):
    """Realization for a klipper printer: its config/extra/component placement classes and its
    klipper-source instrumentation class, deferring to the base tier for the bespok3d-layout
    classes."""

    def placement_destination(self, destination_class: str, name: str) -> str:
        template = _KLIPPER_PLACEMENTS.get(destination_class)
        if template is None:
            return super().placement_destination(destination_class, name)
        return template.format(name=name)

    def instrument_destination(self, instrument_class: str, name: str) -> str:
        template = _KLIPPER_INSTRUMENTS.get(instrument_class)
        if template is None:
            return super().instrument_destination(instrument_class, name)
        return template.format(name=name)

    def classify_commands(self, commands: list[str]) -> list[CommandEffect]:
        markers = self.deferred_service_markers()
        display = self.display_service_tokens()
        return [_classify_one(command, markers, display) for command in commands]

    def deferred_service_markers(self) -> tuple[str, ...]:
        """Device tokens that mark a batchable service command (e.g. the init-script dir, the web
        server). A device jinni supplies its own; the bare klipper tier names none."""
        return ()

    def display_service_tokens(self) -> tuple[str, ...]:
        """Device tokens that mark a display-service restart (it interrupts a print). A device jinni
        supplies its own; the bare klipper tier names none."""
        return ()
