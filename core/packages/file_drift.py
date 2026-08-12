# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which of a plugin's own files no longer hold the bytes its signed manifest recorded.

The same comparison answers two different questions, so the answer belongs to the caller and not to
the shared install spine. A freshly unpacked package that does not match what was signed is refused:
the bytes came from the package and something is wrong with them. The tree already on the printer is
a different matter: another plugin is free to edit a file at runtime (a UI injector rewriting a web
front end is the known case), and the printer keeps no packaged copy to restore from, so a recovery
that refused would cost the user a working plugin and gain nothing.
"""

from pathlib import Path

from .. import jinni_client
from ..intent import normalize_install
from .integrity import CHECKSUM_MISMATCH, IntegrityError, verify_files
from .members import installed_files, rendered_over


def changed_files(plugin_dir: Path, manifest: dict) -> list[str]:
    """The plugin's own files whose bytes differ from the checksum in its signed manifest."""
    inst = normalize_install(manifest.get("install", {}), jinni_client.variant_facts())
    verifiable = installed_files(manifest.get("files", []), rendered_over(inst["templates"]))

    return verify_files(plugin_dir, verifiable)


def refuse_changed_package(plugin_dir: Path, manifest: dict) -> None:
    """Stop an install or an update whose unpacked files are not the ones that were signed."""
    tampered = changed_files(plugin_dir, manifest)
    if tampered:
        raise IntegrityError(manifest["name"], CHECKSUM_MISMATCH, tampered)
