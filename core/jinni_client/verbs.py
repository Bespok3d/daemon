"""The read/resolve half of the jinni contract surface (ADR-0037): the typed wrappers the daemon's
`core/` calls to ask a semantic question or for a realized path (never to mutate the device).

Each verb routes through `dispatch.route` and casts the boundary's dynamic value to its contract
shape. These are the concurrent, inline verbs; the verbs that MUTATE the device live apart in
`actuation.py` (they serialize through the jinni's actuation queue). Both are re-exported as one
facade by this package.
"""
from collections.abc import AsyncGenerator
from typing import cast

import protocol
from protocol import CommandEffect, DeviceHealth

from . import dispatch, transport
from .dispatch import route

# get_jinni / interface_extras are referenced module-qualified (dispatch.get_jinni), never imported
# by name: a test injects the in-process jinni by patching dispatch.get_jinni, and a bound import
# would capture the original and miss the patch. `route` is never patched, so importing it is safe.


def placement_destination(destination_class: str, name: str) -> str:
    return cast(str, route("placement_destination", [destination_class, name]))


def instrument_destination(instrument_class: str, name: str) -> str:
    return cast(str, route("instrument_destination", [instrument_class, name]))


def restart_command(hook: str) -> str | None:
    return cast(str | None, route("restart_command", [hook]))


def render_service_script(service: dict, paths: dict[str, str]) -> str:
    return cast(str, route("render_service_script", [service, paths]))


def render_module_script(kmodule: dict, paths: dict[str, str]) -> str:
    """The kernel-module loader script the daemon writes under the plugin's init.d. The jinni owns
    the device realm (insmod/mknod/rmmod), so it renders the loader; the daemon only places and
    wires it. `paths` supplies the bespok3d layout the module file resolves against."""
    return cast(str, route("render_module_script", [kmodule, paths]))


def device_node_present(path: str) -> bool:
    """Whether a filesystem path (a device node) exists on the printer right now. A cheap read the
    kernel-module mechanism checks a module's outcome with (a `/dev/net/tun` after tun loads); the
    jinni reads its own filesystem (ADR-0037)."""
    return cast(bool, route("device_node_present", [path]))


def classify_module_load(name: str) -> str:
    """A machine token for why a kernel module failed to load (e.g. kernel-module:vermagic-mismatch
    after an OTA kernel bump), or "" when the jinni sees no known cause. The daemon asks only after
    a load reports failure; the jinni reads the device (the kernel ring buffer) and classifies, the
    daemon relays the token and the app localizes it (ADR-0037)."""
    return cast(str, route("classify_module_load", [name]))


def capability_flags() -> set[str]:
    return cast(set[str], route("capability_flags", []))


def variant_facts() -> dict[str, str]:
    """The device facts the variant engine matches a manifest's `when` against (adapter, firmware
    version, arch, board class). A cheap read: unlike `capabilities_report` it runs no port scan, so
    an install or uninstall can resolve which variant to place without a heavy probe."""
    return cast(dict[str, str], route("variant_facts", []))


def classify_commands(commands: list[str]) -> list[CommandEffect]:
    """How each generated start command acts on the device's services. The daemon batches, guards,
    and health-verifies off these flags; the jinni that produced the commands classifies them."""
    return cast(list[CommandEffect], route("classify_commands", [commands]))


def fetch(path: str) -> str | None:
    """Read a device file's current content (the pristine baseline the daemon patches), or None if
    it does not exist. Reading the device file is the jinni's (ADR-0037); the daemon applies the
    diff to the fetched copy in its own tree."""
    return cast("str | None", route("fetch", [path]))


def paths() -> dict[str, str]:
    return cast(dict[str, str], route("paths", []))


def health() -> DeviceHealth:
    """The device's health verdict the safety net judges: each service's readiness + failed
    components, plus the stock broker. The daemon asks once; the jinni probes and reports, retrying
    while a just-restarted service comes back, so this call gets a timeout above the probe budget.
    """
    return cast(DeviceHealth, route("health", [], timeout=protocol.HEALTH_CALL_TIMEOUT_S))


def blocked_actions() -> frozenset[str]:
    """The action TOKENS blocked on the printer right now (empty = nothing blocked). The jinni reads
    the live device state and decides; the daemon relays the tokens and never names a service or a
    state. The print guard checks an op's required tokens against this set."""
    return cast(frozenset[str], route("blocked_actions", []))


async def subscribe_blocked_actions() -> AsyncGenerator[frozenset[str], None]:
    """Stream the blocked-action set, pushed on change. In dev the loaded jinni's watcher runs
    in-process; on the printer the daemon holds one persistent subscribe connection to its jinni
    child. The /ws/print-state route relays each frame to the app verbatim."""
    path = transport.socket_path()
    if path is None:
        async for blocked in dispatch.get_jinni().watch_blocked_actions():
            yield blocked
        return
    async for tokens in protocol.stream(path, protocol.SUBSCRIBE_BLOCKED_ACTIONS):
        yield frozenset(tokens)


def capabilities_report() -> dict:
    """The target facts the daemon relays, with `interface_extras` computed (not self-reported) so a
    custom adapter cannot conceal behaviour beyond the standard interface. In-process the seam folds
    it here; over the socket the jinni service folds it in its own process and we relay it."""
    if transport.socket_path() is None:
        jinni = dispatch.get_jinni()
        return {**jinni.capabilities(), "interface_extras": dispatch.interface_extras(jinni)}
    return cast(dict, route("capabilities_report", []))
