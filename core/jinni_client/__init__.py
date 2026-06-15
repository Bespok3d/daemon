"""The daemon's single door to the jinni (ADR-0037).

The daemon is generic: it orchestrates and never names a device or printer service. The device half
is the jinni, and every generic `core/` module reaches it ONLY through this seam, enforced by
`scripts/generic_daemon_guard.py`. The verbs here are the data contract: the daemon asks a semantic
question or for a realized path/command, the jinni answers with a serializable value. No live jinni
object leaks past this module.

The transport is pluggable (`transport.py`): in dev the loaded jinni answers in-process; on the
printer the daemon spawns its jinni child (`supervisor.py`) and every verb routes over the Unix
socket. The verbs are identical either way; each casts the boundary's dynamic value to its contract
shape.
"""
from collections.abc import AsyncIterator
from typing import Any, cast

from jinni import interface_extras, protocol
from jinni.contracts import CommandEffect, DeviceHealth
from jinni.health import HEALTH_PROBE_BUDGET_S
from jinni.loader import get_jinni

from . import transport
from .supervisor import default_socket_path, start_jinni, stop_jinni
from .transport import use_in_process, use_socket

# `health` is the one verb that blocks while a restarted service comes back (up to
# HEALTH_PROBE_BUDGET_S of retry sleeps, plus the probe attempts themselves), unlike the other verbs
# which answer at once. Its socket timeout is sized above that budget so a slow-but-legitimate
# restart never surfaces as "no reply from the jinni for 'health'". The margin covers the probe
# round-trips the budget does not count.
_HEALTH_PROBE_OVERHEAD_S = 30.0
_HEALTH_CALL_TIMEOUT_S = HEALTH_PROBE_BUDGET_S + _HEALTH_PROBE_OVERHEAD_S

__all__ = [
    "default_socket_path", "start_jinni", "stop_jinni", "use_in_process", "use_socket",
    "placement_destination", "instrument_destination", "restart_command", "render_service_script",
    "capability_flags", "classify_commands", "paths", "capabilities_report", "health",
    "blocked_actions", "subscribe_blocked_actions",
]


def _dispatch(verb: str, args: list[Any], timeout: float | None = None) -> Any:
    """Route one verb to the jinni. In dev the loaded jinni answers in-process; once the daemon has
    spawned its jinni child the call goes over the socket. Returns the contract value as Any (a
    dynamic call or a decoded wire frame); each verb casts it to its shape at the boundary.
    `timeout` overrides the socket reply timeout for a verb that may block longer than usual."""
    path = transport.socket_path()
    if path is None:
        return getattr(get_jinni(), verb)(*args)
    if timeout is None:
        return protocol.call(path, verb, args)
    return protocol.call(path, verb, args, timeout)


def placement_destination(destination_class: str, name: str) -> str:
    return cast(str, _dispatch("placement_destination", [destination_class, name]))


def instrument_destination(instrument_class: str, name: str) -> str:
    return cast(str, _dispatch("instrument_destination", [instrument_class, name]))


def restart_command(hook: str) -> str | None:
    return cast(str | None, _dispatch("restart_command", [hook]))


def render_service_script(service: dict, paths: dict[str, str]) -> str:
    return cast(str, _dispatch("render_service_script", [service, paths]))


def capability_flags() -> set[str]:
    return cast(set[str], _dispatch("capability_flags", []))


def classify_commands(commands: list[str]) -> list[CommandEffect]:
    """How each generated start command acts on the device's services. The daemon batches, guards,
    and health-verifies off these flags; the jinni that produced the commands classifies them."""
    return cast(list[CommandEffect], _dispatch("classify_commands", [commands]))


def paths() -> dict[str, str]:
    return cast(dict[str, str], _dispatch("paths", []))


def health() -> DeviceHealth:
    """The device's health verdict the safety net judges: each service's readiness + failed
    components, plus the stock broker. The daemon asks once; the jinni probes and reports, retrying
    while a just-restarted service comes back, so this call gets a timeout above the probe budget.
    """
    return cast(DeviceHealth, _dispatch("health", [], timeout=_HEALTH_CALL_TIMEOUT_S))


def blocked_actions() -> frozenset[str]:
    """The action TOKENS blocked on the printer right now (empty = nothing blocked). The jinni reads
    the live device state and decides; the daemon relays the tokens and never names a service or a
    state. The print guard checks an op's required tokens against this set."""
    return cast(frozenset[str], _dispatch("blocked_actions", []))


async def subscribe_blocked_actions() -> AsyncIterator[frozenset[str]]:
    """Stream the blocked-action set, pushed on change. In dev the loaded jinni's watcher runs
    in-process; on the printer the daemon holds one persistent subscribe connection to its jinni
    child. The /ws/print-state route relays each frame to the app verbatim."""
    path = transport.socket_path()
    if path is None:
        async for blocked in get_jinni().watch_blocked_actions():
            yield blocked
        return
    async for tokens in protocol.stream(path, protocol.SUBSCRIBE_BLOCKED_ACTIONS):
        yield frozenset(tokens)


def capabilities_report() -> dict:
    """The target facts the daemon relays, with `interface_extras` computed (not self-reported) so a
    custom adapter cannot conceal behaviour beyond the standard interface. In-process the seam folds
    it here; over the socket the jinni service folds it in its own process and we relay it."""
    if transport.socket_path() is None:
        jinni = get_jinni()
        return {**jinni.capabilities(), "interface_extras": interface_extras(jinni)}
    return cast(dict, _dispatch("capabilities_report", []))
