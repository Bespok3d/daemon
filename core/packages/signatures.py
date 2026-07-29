# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The detached manifest signature a .b3 carries, as it survives on the printer.

`manifest.json.sig` is extracted with the rest of the archive and never removed, so a plugin the
daemon installed keeps the signature its package shipped with. Reporting which plugins hold one lets
a signature be checked against a key later, after the fact, for packages already on the device.

Presence is a filesystem fact and the daemon owns the filesystem (ADR-0037), so it is answered here
rather than asked of the jinni. Nothing here verifies anything: a stored signature says the package
carried one, never that it is valid.
"""

from pathlib import Path

SIGNATURE_MEMBER = "manifest.json.sig"


def plugins_with_stored_signature(plugin_root: Path) -> list[str]:
    """The installed plugin IDs whose directory still holds the signature its package shipped."""
    if not plugin_root.is_dir():
        return []
    return sorted(
        plugin_dir.name
        for plugin_dir in plugin_root.iterdir()
        if (plugin_dir / SIGNATURE_MEMBER).is_file()
    )
