# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Settle who owns each file a plugin patches, before the first fragment is applied."""

from collections.abc import Callable
from pathlib import Path

from .patch_handover import adoption_phase
from .patch_relinquish import relinquish_phase

PhaseAnnouncer = Callable[[dict], dict]


def ownership_phases(plugin_root: Path, plugin_dir: Path, patches: list[dict],
                     vars: dict[str, str], announce: PhaseAnnouncer) -> list[dict]:
    """Files this plugin has stopped patching go back to stock while it still holds their originals,
    then it takes on the true original of every file it does patch, rather than another plugin's
    output. It stops at the first of the two that fails, so a file that could not be put back is
    never then adopted from its own patched text. A file whose original can neither be put back nor
    established stops the install: patching it would bake another plugin's changes in as this one's
    baseline, and the caller settles the half-run install by taking the plugin back off the
    printer."""
    relinquished = announce(relinquish_phase(plugin_dir, patches, vars))
    if not relinquished["ok"]:
        return [relinquished]
    return [relinquished, announce(adoption_phase(plugin_root, plugin_dir, patches, vars))]
