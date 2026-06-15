"""Typed shapes the jinni interface returns to the daemon.

A dataclass here crosses the jinni boundary: the daemon asks, the device jinni fills it in. Keeping
them in one leaf module lets the generic daemon AND an adapter import the shape without pulling in
the jinni tiers.
"""
from dataclasses import dataclass

# Service names the daemon's safety net reads out of a DeviceHealth report. They are the domain of a
# Klipper plugin manager (generic, not a device fact), declared once so the jinni that fills the
# report and the daemon that reads it cannot drift.
KLIPPER_SERVICE = "klipper"
MOONRAKER_SERVICE = "moonraker"

# Blocked-action TOKENS (ADR-0037): the machine vocabulary the jinni emits for "what is blocked
# right now". The jinni decides; the daemon relays the token verbatim and the CLIENT localizes it,
# never turning one into a sentence. A token marks a device-realm action a running print forbids:
# restarting Klipper, Moonraker, or the printer's display. The jinni both reports the live blocked
# set and tags each command with the token it would trigger, so the print guard is set membership.
RESTART_KLIPPER = "restart-klipper"
RESTART_MOONRAKER = "restart-moonraker"
RESTART_DISPLAY = "restart-display"


@dataclass(frozen=True)
class ServiceHealth:
    """One device service's health after a risky op: whether it is ready/usable, a human detail, and
    (for a service like Moonraker whose components load dynamically) any that failed or only warned.
    A service can be reachable yet report a failed component, which plain reachability misses, so
    the safety net judges on these."""
    ready: bool
    detail: str
    failed_components: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass
class DeviceHealth:
    """The jinni's health verdict the daemon's safety net judges and acts on. The daemon asks one
    semantic question ("is the device healthy?") instead of probing each service or naming a port.

    `services` is keyed by service name (KLIPPER_SERVICE, MOONRAKER_SERVICE). `diagnosis` is a
    machine TOKEN for a NON-plugin cause when the jinni knows one (e.g. a stock-firmware service the
    printer needs is down); the safety net relays it verbatim instead of blaming a plugin, and the
    CLIENT localizes it, never the daemon. Empty means no such cause. The token vocabulary is the
    device jinni's (a device fact like the U1's MQTT broker lives behind it, not in a daemon flag).
    """
    services: dict[str, ServiceHealth]
    diagnosis: str = ""

    @property
    def healthy(self) -> bool:
        """Usable: every service ready AND none reporting a failed component."""
        return all(service.ready and not service.failed_components
                   for service in self.services.values())


@dataclass(frozen=True)
class ControlScript:
    """A control script the daemon writes into the persistent bespok3d tree at startup.

    `path` is the absolute destination (in the persistent tree, so it survives a daemon redeploy),
    `content` the rendered script text, `mode` the file mode (e.g. 0o755 for an executable).
    """
    path: str
    content: str
    mode: int


@dataclass(frozen=True)
class CommandEffect:
    """How one expanded start command acts on the device's services, judged by the jinni that
    produced it. The daemon reads these flags and orchestrates; it never inspects the command string
    itself (ADR-0037: the daemon does not classify commands or name services).

    `deferrable`: a service restart the daemon batches to the op's end instead of running inline.
    `restarts_klipper` / `restarts_moonraker`: the daemon waits for that service to come back and
    arms the safety net around it.
    `blocking_token`: the blocked-action token this command would trigger (RESTART_KLIPPER /
    RESTART_MOONRAKER / RESTART_DISPLAY), or None when it touches no print-interrupting service. The
    print guard refuses the op when this token is in the jinni's current blocked set.
    """
    deferrable: bool
    restarts_klipper: bool
    restarts_moonraker: bool
    blocking_token: str | None
