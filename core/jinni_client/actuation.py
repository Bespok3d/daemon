# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The actuation half of the jinni contract surface (ADR-0037): the verbs that MUTATE the device.

Each serializes through the jinni's actuation queue on the other side (the jinni service's
ACTUATION_VERBS) and runs off its event loop, so two ops never bounce a service at once while reads
stay concurrent. The daemon resolves, sequences, and reports; the jinni performs the device-realm
action. Kept apart from the read/resolve wrappers (`verbs.py`) so neither file grows past one
concern; both share the `route` mechanism and are re-exported as one facade by this package.
"""
from typing import cast

import protocol
from protocol import ActionResult

from .dispatch import route


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
