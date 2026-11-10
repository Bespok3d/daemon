# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Putting back an installed plugin's files that changed on the printer, from a zip of just them.

The zip carries no manifest of its own: what vouches for every file in it is the manifest the plugin
was installed with, which lists each file's sha256. So every member must be one of the files that
manifest lists as kept on disk, must sit in a folder inside the plugin dir, and must hold exactly
the bytes listed for it, all checked before a byte is written. Nothing is re-applied: the files go
back where install put them, and install's permission fix runs over them again.
"""

import zipfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from .archive import fix_ownership
from .damaged_zip import member_sha256, opened_restore_zip
from .extraction import write_members
from .file_drift import verifiable_files
from .integrity import CHECKSUM_MISMATCH, ESCAPING_MEMBER, UNDECLARED_MEMBER, IntegrityError
from .members import lands_inside, walks_only_down
from .print_guard import guard_no_print
from .unpacked_size import refuse_package_that_does_not_fit


def restore_files(
    plugin_dir: Path, installed_manifest: dict, restore_archive: BinaryIO, runtime_user: str,
) -> list[str]:
    """Write the zip's files over the plugin's own and return their paths, or refuse the zip
    whole."""
    guard_no_print()
    with opened_restore_zip(restore_archive) as restore_zip:
        members = sorted({name for name in restore_zip.namelist() if not name.endswith("/")})
        # Measured first: it reads only the zip's own directory, while the next check unpacks
        # every member to hash it.
        refuse_package_that_does_not_fit(restore_zip, plugin_dir, members)
        _refuse_unsigned_members(restore_zip, plugin_dir, members, installed_manifest)
        _write_owned_by_runtime_user(restore_zip, plugin_dir, members, runtime_user)
    return members


def _write_owned_by_runtime_user(
    restore_zip: zipfile.ZipFile, plugin_dir: Path, members: list[str], runtime_user: str,
) -> None:
    """The ownership fix runs even when a write fails part way: the files already written are
    root's until it does, and the plugin cannot read them."""
    try:
        write_members(restore_zip, plugin_dir, members)
    finally:
        ownership = fix_ownership(plugin_dir, runtime_user)
    if not ownership["ok"]:
        raise RuntimeError(f"the restored files of {plugin_dir.name} kept the wrong permissions")


def _refuse_unsigned_members(
    restore_zip: zipfile.ZipFile, plugin_dir: Path, members: list[str], installed_manifest: dict,
) -> None:
    signed = {entry["path"]: entry.get("sha256") for entry in verifiable_files(installed_manifest)}
    plugin_id = plugin_dir.name
    undeclared = [name for name in members if name not in signed]
    if undeclared:
        raise IntegrityError(plugin_id, UNDECLARED_MEMBER, undeclared)
    escaping = _escaping_folders(plugin_dir, members)
    if escaping:
        raise IntegrityError(plugin_id, ESCAPING_MEMBER, escaping)
    mismatched = [name for name in members if member_sha256(restore_zip, name) != signed[name]]
    if mismatched:
        raise IntegrityError(plugin_id, CHECKSUM_MISMATCH, mismatched)


def _escaping_folders(plugin_dir: Path, members: list[str]) -> list[str]:
    return [name for name in members if not _written_in_a_contained_folder(plugin_dir, name)]


def _written_in_a_contained_folder(plugin_dir: Path, name: str) -> bool:
    """Only a member's folder must stay inside the plugin dir. The file itself may now be a link
    out of it, which the hashes route answers as missing so the app sends it back: the write
    unlinks such a link and puts the file in its place, it never follows it. A `..` anywhere in
    the name is refused, because the zip writes such a name at another path than this measures."""
    return walks_only_down(name) and lands_inside(plugin_dir, str(PurePosixPath(name).parent))
