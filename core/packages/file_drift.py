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
from .members import declared_entries, installed_files, rendered_over
from .own_file import own_file_sha256


def verifiable_files(manifest: dict) -> list[dict]:
    """The manifest entries whose file the printer keeps exactly as the packer hashed it."""
    resolved_install = normalize_install(manifest.get("install", {}), jinni_client.variant_facts())
    declared = declared_entries(manifest.get("files", []))
    return installed_files(declared, rendered_over(resolved_install["templates"]))


def file_hashes(plugin_dir: Path, manifest: dict) -> dict[str, str | None]:
    """The sha256 of each of the plugin's kept files by manifest path, None for one the printer
    does not hold as the plugin's own regular file."""
    return {entry["path"]: own_file_sha256(plugin_dir, entry["path"])
            for entry in verifiable_files(manifest)}


def changed_files(plugin_dir: Path, manifest: dict) -> list[str]:
    """The plugin's own files whose bytes differ from the checksum in its signed manifest."""
    return verify_files(plugin_dir, verifiable_files(manifest))


def refuse_changed_package(plugin_dir: Path, manifest: dict) -> None:
    """Stop an install or an update whose unpacked files are not the ones that were signed."""
    tampered = changed_files(plugin_dir, manifest)
    if tampered:
        raise IntegrityError(manifest["name"], CHECKSUM_MISMATCH, tampered)
