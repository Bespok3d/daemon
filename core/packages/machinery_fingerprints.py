# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The fingerprint each machinery package carried, as the signed manifest kept beside the daemon
records it.

The daemon and the jinni are not installed as plugins, so no plugin directory keeps their manifest.
The adapter that places them writes each one's signed manifest to its own file under the daemon's
directory, named after the package, once the package's files are in place. The app keys the
machinery it ships by the same names, so a daemon or a jinni rebuilt at the same version is still
offered as an update. A file that is missing, torn or carries no fingerprint is left out: the app
then has nothing to compare and treats that package as it did before fingerprints existed.
"""

from pathlib import Path

from ..json_file import read_json
from .fingerprints import FINGERPRINT_FIELD

MACHINERY_MANIFEST_DIR = Path(__file__).resolve().parents[2] / "manifests"
MANIFEST_SUFFIX = ".json"


def machinery_fingerprints(manifest_dir: Path) -> dict[str, str]:
    """Machinery package name to the fingerprint its kept manifest carries."""
    kept_manifests = {
        manifest_path.stem: read_json(manifest_path)
        for manifest_path in sorted(manifest_dir.glob(f"*{MANIFEST_SUFFIX}"))
    }
    return {
        package_name: manifest[FINGERPRINT_FIELD]
        for package_name, manifest in kept_manifests.items()
        if isinstance(manifest, dict) and isinstance(manifest.get(FINGERPRINT_FIELD), str)
    }
