# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The fingerprint each installed plugin's package carried, as its stored manifest records it.

b3-builder writes `fingerprint` into the signed manifest when it packs a .b3, and the manifest is
extracted onto the printer unchanged. The app compares it with the fingerprint of the published
package, so a rebuild at the same version is still offered as an update. It is read back, never
recomputed: a value worked out here from the files on disk would describe the printer, not the
package that was installed. A package packed before fingerprints existed carries none and is left
out rather than given a stand-in.
"""

from pathlib import Path

from .manifest import installed_manifests

FINGERPRINT_FIELD = "fingerprint"


def installed_fingerprints(plugin_root: Path) -> dict[str, str]:
    """Installed plugin ID to the fingerprint its stored manifest carries."""
    return {
        plugin_id: manifest[FINGERPRINT_FIELD]
        for plugin_id, manifest in installed_manifests(plugin_root).items()
        if isinstance(manifest.get(FINGERPRINT_FIELD), str)
    }
