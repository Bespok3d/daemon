"""The live-probing facet of the jinni: read the running device and judge what may be done now.

Reachability (`port_listening`/`service_get`) and the live print read (`print_active`) delegate to
the loopback probe implementations in `inspection.py`. `blocked_actions()` is the live blocked
TOKEN set the print guard checks (ADR-0037): the jinni decides what a running print forbids and
names it as machine tokens, never prose. The base tier is a generic box that blocks nothing; the
klipper tier reads the device and the composition root assembles the token set.
"""
import asyncio
from collections.abc import AsyncIterator

from . import inspection
from .layout import Layout

# Klipper print_stats states in which a print is running and a service restart would interrupt it.
_ACTIVE_PRINT_STATES = ("printing", "paused")


class Probing:
    def port_listening(self, port: int) -> bool:
        """Whether a localhost TCP port is open. The jinni reaches the printer, so this is the
        device's concern; a device with an unusual probe overrides it."""
        return inspection.tcp_port_listening(port)

    def service_get(self, url: str, timeout: int = 3) -> tuple[bool, str]:
        """GET a localhost service URL: (up, body). An auth-required answer still means up; a
        connection error means not-yet-up. Overridable for a device whose services differ."""
        return inspection.http_service_get(url, timeout)

    def print_active(self) -> tuple[bool, str]:
        """Whether a print is running, and the raw state string. A generic box prints nothing; the
        klipper tier reads it live."""
        return False, ""

    def is_active_print_state(self, state: str) -> bool:
        """Whether a print-state string counts as a running print. Base: never (no print states)."""
        return False

    def blocked_actions(self) -> frozenset[str]:
        """The action TOKENS blocked on the printer right now (empty = nothing blocked). A generic
        box has no print to protect; the klipper composition root reads the live state."""
        return frozenset()

    async def watch_blocked_actions(self) -> AsyncIterator[frozenset[str]]:
        """Push the blocked-action set on change. A generic box never changes: emit the empty set
        once, then idle. The klipper composition root subscribes to the live print state."""
        yield frozenset()
        await asyncio.Event().wait()

    def _candidate_ports(self) -> dict[int, str]:
        return dict(inspection.GENERIC_PORTS)


class KlipperProbing(Layout, Probing):
    """Live probing for a klipper printer: it reads the print state from Klipper's API socket (so it
    inherits Layout for the socket path) and adds the Moonraker port to the candidate set. The
    blocked-action token set is assembled on the composition root (it needs the display tokens from
    the realization facet), so it lives in jinni/klipper.py, not here."""

    def print_active(self) -> tuple[bool, str]:
        """Live print state: Klipper's API socket first (auth-immune), Moonraker HTTP fallback."""
        state = inspection.print_state(self.paths().get("KLIPPER_UDS", ""))
        return self.is_active_print_state(state), state

    def is_active_print_state(self, state: str) -> bool:
        return state in _ACTIVE_PRINT_STATES

    def _candidate_ports(self) -> dict[int, str]:
        return {**inspection.GENERIC_PORTS, inspection.MOONRAKER_PORT: "Moonraker API"}
