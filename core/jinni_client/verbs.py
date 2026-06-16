"""The jinni contract verb surface (ADR-0037): the typed wrappers the daemon's `core/` calls.

Each verb routes through `dispatch.route` and casts the boundary's dynamic value to its contract
shape. Read/resolve verbs ask a semantic question or for a realized path; actuation verbs mutate the
device (the daemon resolves, sequences, and reports; the jinni performs the device-realm action).
"""
from collections.abc import AsyncIterator
from typing import cast

import protocol
from protocol import ActionResult, CommandEffect, DeviceHealth

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


def capability_flags() -> set[str]:
    return cast(set[str], route("capability_flags", []))


def classify_commands(commands: list[str]) -> list[CommandEffect]:
    """How each generated start command acts on the device's services. The daemon batches, guards,
    and health-verifies off these flags; the jinni that produced the commands classifies them."""
    return cast(list[CommandEffect], route("classify_commands", [commands]))


def run_actions(commands: list[str]) -> list[ActionResult]:
    """Run the resolved device actions (a plugin's start, a core-service restart, a stop command) in
    order, one ActionResult per command. The daemon resolves, groups, and dedupes the commands and
    reports the results; executing one (the device-realm subprocess) is the jinni's (ADR-0037). The
    reply timeout is generous: a restart or a slow start can outlast the default frame budget."""
    return cast(list[ActionResult], route("run_actions", [commands], timeout=protocol.ACTION_CALL_TIMEOUT_S))  # noqa: E501


def wire(plugin_dir: str, links: list[dict[str, str]]) -> list[ActionResult]:
    """Symlink each placed file (`{source, destination}`, both resolved by the daemon) into the
    system, backing up any stock original, and record the declarative reversion to the plugin's
    wiring.json. Creating and backing up a device symlink is the jinni's actuation (ADR-0037)."""
    return cast(list[ActionResult], route("wire", [plugin_dir, links], timeout=protocol.ACTION_CALL_TIMEOUT_S))  # noqa: E501


def unwire(plugin_dir: str, destinations: list[str]) -> list[ActionResult]:
    """Drop the symlinks the daemon resolved and restore any stock original from its backup, the
    inverse of wire, when a plugin is taken off the system."""
    return cast(list[ActionResult], route("unwire", [plugin_dir, destinations], timeout=protocol.ACTION_CALL_TIMEOUT_S))  # noqa: E501


def fetch(path: str) -> str | None:
    """Read a device file's current content (the pristine baseline the daemon patches), or None if
    it does not exist. Reading the device file is the jinni's (ADR-0037); the daemon applies the
    diff to the fetched copy in its own tree."""
    return cast("str | None", route("fetch", [path]))


def write_files(plugin_dir: str, writes: list[dict]) -> list[ActionResult]:
    """Write each `{path, content, restore_from?}` to the device: a patched source the daemon built,
    or a pristine baseline on restore. Writing the device file is the jinni's actuation; a write
    that carries `restore_from` records its undo in the plugin's wiring.json."""
    return cast(list[ActionResult], route("write_files", [plugin_dir, writes], timeout=protocol.ACTION_CALL_TIMEOUT_S))  # noqa: E501


def prune_dead_config_links() -> list[str]:
    """Drop bespok3d include symlinks whose target no longer exists (junk from an earlier uninstall
    that breaks a service's include glob). The jinni knows its include dirs; returns the removed
    paths so the restart self-heal can report them."""
    return cast(list[str], route("prune_dead_config_links", [], timeout=protocol.ACTION_CALL_TIMEOUT_S))  # noqa: E501


def remove_bespok3d_includes() -> None:
    """Remove the bespok3d include lines from the printer's own config. Enrollment wrote them
    client-side, so the daemon never edits the device config (ADR-0037): this is the jinni's unwire,
    on deactivate and teardown."""
    route("remove_bespok3d_includes", [], timeout=protocol.ACTION_CALL_TIMEOUT_S)


def prune_bespok3d_config_dir() -> None:
    """Take back the bespok3d include dir on teardown (our symlinks and any now-empty dirs), keeping
    any user files. The jinni knows the dir."""
    route("prune_bespok3d_config_dir", [], timeout=protocol.ACTION_CALL_TIMEOUT_S)


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


async def subscribe_blocked_actions() -> AsyncIterator[frozenset[str]]:
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
