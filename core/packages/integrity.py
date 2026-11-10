# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Integrity: verify a plugin's on-disk files against the sha256 the packer recorded in the
manifest, before any placement or ownership phase touches them. `b3-builder`'s `packPlugin` writes
`sha256` for every entry in `manifest["files"]` at pack time; this module is the daemon-side check
that closes the loop, so a corrupted or truncated `.b3` extraction is refused before it is wired
into the printer.
"""

import hashlib
from io import BufferedIOBase
from pathlib import Path

# Why the archive did not match its signed manifest. Relayed as TOKENS the client localizes
# (ADR-0037); the exception message spells them out for the daemon's own logs, never for the user.
CHECKSUM_MISMATCH = "checksum_mismatch"
UNDECLARED_MEMBER = "undeclared_member"
ESCAPING_MEMBER = "escaping_member"
ESCAPING_PLUGIN_ID = "escaping_plugin_id"
MISSING_MEMBER = "missing_member"


class IntegrityError(Exception):
    """Install was refused because the package did not match its signed manifest: a file whose
    sha256 differs, a member the manifest never listed, a member aimed outside the plugin dir, a
    plugin name that is not a plain directory name, or a listed file the package left out that the
    printer does not already hold as signed."""

    def __init__(self, plugin_id: str, reason: str, paths: list[str]) -> None:
        self.plugin_id = plugin_id
        self.reason = reason
        self.paths = paths
        super().__init__(f"{plugin_id} failed integrity check ({reason}): {', '.join(paths)}")


def verify_files(plugin_dir: Path, manifest_files: list[dict]) -> list[str]:
    """Return the manifest paths whose on-disk file is missing or whose sha256 does not match."""
    return [entry["path"] for entry in manifest_files if not _matches(plugin_dir, entry)]


def _matches(plugin_dir: Path, entry: dict) -> bool:
    """An entry the packer never hashed cannot be vouched for, so a missing sha256 is a mismatch."""
    target = plugin_dir / entry["path"]
    recorded: object = entry.get("sha256")
    return target.exists() and recorded == sha256_of(target)


def sha256_of(target: Path) -> str:
    """The hex sha256 of a file."""
    with target.open("rb") as stream:
        return sha256_of_stream(stream)


def sha256_of_stream(stream: BufferedIOBase) -> str:
    """The hex sha256 of an open file, read in chunks so a large binary never sits whole in
    memory."""
    return hashlib.file_digest(stream, "sha256").hexdigest()
