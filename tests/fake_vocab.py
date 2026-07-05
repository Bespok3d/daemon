"""The klipper-jinni vocabulary a fake emits, as the daemon receives it over the socket: placement
classes, restart commands, and command classification. Plain strings the daemon relays and never
authors. Kept apart from the fake jinni classes so each stays small.
"""
from protocol import CommandEffect

KLIPPER = "klipper"
MOONRAKER = "moonraker"
RESTART_KLIPPER = "restart-klipper"
RESTART_MOONRAKER = "restart-moonraker"
RESTART_DISPLAY = "restart-display"

PLACEMENTS = {
    "klipper-config": "$BESPOK3D_KLIPPER/{name}",
    "moonraker-config": "$BESPOK3D_MOONRAKER/{name}",
    "klipper-extra": "$KLIPPER_EXTRAS/{name}",
    "moonraker-component": "$MOONRAKER_COMPONENTS/{name}",
    "system-bin": "$BESPOK3D/bin/{name}",
    "web-location": "$BESPOK3D/etc/nginx/locations/{name}",
    "kernel-module": "$BESPOK3D/lib/modules/{name}",
}
INSTRUMENTS = {"klipper-source": "$KLIPPER_SRC/{name}"}
RESTART_COMMANDS = {
    "klipper": "/etc/init.d/S60klipper restart",
    "moonraker": "/etc/init.d/S61moonraker restart",
    "web": "/usr/sbin/nginx -s reload",
    "lmd": "$BESPOK3D/etc/init.d/lmdctl restart",
}
KLIPPER_PATH_KEYS = (
    "BESPOK3D_KLIPPER", "BESPOK3D_MOONRAKER", "KLIPPER_SRC", "KLIPPER_EXTRAS",
    "MOONRAKER_COMPONENTS", "PRINTER_CFG", "MOONRAKER_CFG",
)
_MARKERS = ("init.d", "nginx")
_DISPLAY_TOKENS = ("lmdctl",)


def _blocking_token(restarts: tuple[str, ...], display: bool) -> str | None:
    if KLIPPER in restarts:
        return RESTART_KLIPPER
    if MOONRAKER in restarts:
        return RESTART_MOONRAKER
    return RESTART_DISPLAY if display else None


def classify(command: str) -> CommandEffect:
    if not any(verb in command for verb in ("restart", "start", "reload")):
        return CommandEffect(deferrable=False, restarts_services=(), blocking_token=None)
    restarts = tuple(name for name in (KLIPPER, MOONRAKER) if name in command)
    display = any(token in command for token in _DISPLAY_TOKENS)
    token = _blocking_token(restarts, display)
    deferrable = token is not None or any(marker in command for marker in _MARKERS)
    return CommandEffect(deferrable=deferrable, restarts_services=restarts, blocking_token=token)
