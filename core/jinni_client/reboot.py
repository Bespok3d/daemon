# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The reboot verbs of the jinni contract (ADR-0037): the states only a power cycle clears, and the
reboot that clears them.

Which states those are is device knowledge: the jinni recognises them, the daemon only asks and
relays. Kept apart from the read/resolve wrappers (`verbs.py`) so neither file grows past one
concern.
"""
from typing import cast

from .dispatch import route


def reboot_required() -> list[str]:
    """The tokens for every state this printer has got into that only a power cycle clears, empty
    when there is none. Which states those are is device knowledge the daemon must never learn: a
    printer whose jinni recognises none answers empty and nothing is offered to the user."""
    return cast(list[str], route("reboot_required", []))


def watch_line(line: str) -> str | None:
    """The token of a state only a power cycle clears when this live kernel log line reports one,
    None otherwise. The daemon only relays the line; recognising it is device knowledge."""
    return cast("str | None", route("watch_line", [line]))


def reboot_printer() -> None:
    """Ask the printer to reboot. The jinni starts the reboot detached and answers at once, so the
    call returns before the printer goes down."""
    route("reboot_printer", [])
