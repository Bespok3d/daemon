# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The original of a patched file a plugin takes over, worked out from the file the printer runs
NOW.

After a firmware update every kept copy is the OLD firmware's file, while the live file is the new
firmware's, maybe with another plugin's patches on it. So the original is always the live file with
the other owners' patches taken off, never a kept copy as it is: taking a kept copy over as it was
put a firmware 2.0 file back on a printer running firmware 2.1.

The result counts only when each owner's patches are proven off it: they came off it, they fit it
again, or the owner cannot have them on the file. A switched-off owner took its patches off when it
was switched off. In a recovery, patches that neither fit the file nor come off it belong to a
firmware the printer no longer runs: recovery treats a plugin's own patches the same way.

Whether a recovery is running is scoped to the re-apply that recovery runs (`inside_a_recovery()`),
the same way `manifest_warnings` scopes its collection, so no install signature carries the flag
down to the one check that needs it.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from .baseline import is_stock, without_patches
from .switched_off_marker import DEACTIVATED_MARKER

_recovery_running: ContextVar[bool] = ContextVar("recovery_running", default=False)


@contextmanager
def inside_a_recovery() -> Iterator[None]:
    """Mark the block as a recovery's re-apply of one plugin."""
    scope = _recovery_running.set(True)
    try:
        yield
    finally:
        _recovery_running.reset(scope)


def original_of_the_live_file(live_text: str, owners: dict[Path, list[Path]]) -> str | None:
    """`live_text` with each owner's patches taken off, or None when an owner's patches may still
    be on it. An owner whose patches did not come off is checked on its own: two owners' patches
    touching the same lines never fit one file together, even when each one is off it."""
    original, still_on = _without_owners_patches(live_text, owners)
    unproven = [owner for owner in still_on if not is_stock(original, owners[owner])]
    if _recovery_running.get() or all((owner / DEACTIVATED_MARKER).exists() for owner in unproven):
        return original
    return None


def _without_owners_patches(text: str, owners: dict[Path, list[Path]]) -> tuple[str, list[Path]]:
    """`text` with every owner's patches that come off it taken off, and the owners whose patches
    did not. The owners are not tried in a fixed order: an owner's patches whose context holds
    another owner's change come off only after that owner's last, so each round takes off whichever
    comes off first, until none does."""
    peeled, still_on = text, list(owners)
    while True:
        peel = next(((owner, taken_off) for owner in still_on
                     if (taken_off := without_patches(peeled, owners[owner])) is not None), None)
        if peel is None:
            return peeled, still_on
        peeled_owner, peeled = peel
        still_on = [owner for owner in still_on if owner != peeled_owner]
