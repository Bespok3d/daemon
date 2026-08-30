# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The plugins an operation walked past because their own manifest could not be read.

A torn manifest never stops an install, an update or a recovery: the plugin carrying it declares no
service, declares no conflict, orders nowhere and has no log, so the plugins next to it still go
through. Skipping it in silence is what left the user with a plugin that quietly does nothing, so an
operation collects the plugins it could not account for and its answer carries them back.

Collection is scoped to one operation. Outside `collecting_torn_plugins()` nothing is kept, so the
paths that read one named manifest for their own reasons (tailing a plugin's log, guarding a print)
record nothing, and no caller has to thread a collector down to the one read that failed.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

UNREADABLE_MANIFEST = "manifest-unreadable"

_torn_this_operation: ContextVar[dict[str, str] | None] = ContextVar(
    "torn_plugins_this_operation", default=None,
)


@contextmanager
def collecting_torn_plugins() -> Iterator[dict[str, str]]:
    """Collect the torn plugins met inside the block, keyed by plugin directory name and filled as
    the block runs. Each operation holds its own collection: two requests at once cannot land in
    each other's, and blocking work handed to a worker thread fills the one it was started from,
    because the thread is handed a copy of the context holding it."""
    met: dict[str, str] = {}
    scope = _torn_this_operation.set(met)
    try:
        yield met
    finally:
        _torn_this_operation.reset(scope)


def note_torn_plugin(plugin_dir: Path, problem: str) -> None:
    """Record one plugin whose manifest could not be read, keeping the first reason met for it."""
    met = _torn_this_operation.get()
    if met is not None:
        met.setdefault(plugin_dir.name, problem)


def torn_plugin_warnings(met: dict[str, str]) -> list[dict[str, str]]:
    """The collected plugins in the shape the answer carries them in, in the order they were met."""
    return [{"plugin": plugin, "problem": UNREADABLE_MANIFEST, "detail": detail}
            for plugin, detail in met.items()]
