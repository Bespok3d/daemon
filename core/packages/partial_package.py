# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A package may leave out the files the printer already holds exactly as signed.

An update that changes a few files need not carry the rest across the network again: the manifest
still lists every file with its sha256, so a listed file the zip leaves out is vouched for by the
copy on disk, as long as that copy holds those exact bytes. The check runs before a byte is written,
so a left-out file that is missing or different refuses the whole package and the install on the
printer stays as it was. A first install has nothing on disk to vouch, so any file it leaves out is
refused, except a template's render target: install writes that file itself.
"""

from pathlib import Path

from .extraction import entry_the_write_unlinks
from .file_drift import verifiable_files
from .integrity import MISSING_MEMBER, IntegrityError
from .members import declared_paths, is_doc_member
from .own_file import own_file_sha256

_InodeIdentity = tuple[int, int]


def refuse_unbacked_left_out_files(
    plugin_dir: Path, deployed_members: list[str], manifest: dict,
) -> None:
    """Raise unless every listed file the package left out is already on disk as signed."""
    left_out = _left_out_paths(deployed_members, manifest)
    if not left_out:
        return
    replaced = _replaced_by_the_write(plugin_dir, deployed_members)
    unbacked = sorted(
        entry["path"] for entry in verifiable_files(manifest)
        if entry["path"] in left_out and not _backed_on_disk(plugin_dir, entry, replaced)
    )
    if unbacked:
        raise IntegrityError(plugin_dir.name, MISSING_MEMBER, unbacked)


def _left_out_paths(deployed_members: list[str], manifest: dict) -> set[str]:
    """The declared paths the zip does not carry. Found before `verifiable_files`, so a full
    package never reaches the variant read the render targets need."""
    declared = declared_paths(manifest.get("files", []))
    return {path for path in declared if not is_doc_member(path)} - set(deployed_members)


def _replaced_by_the_write(plugin_dir: Path, deployed_members: list[str]) -> set[_InodeIdentity]:
    """What writing the members unlinks. Taken by inode, not by name: the write joins a name with
    pathlib, which tidies `./` and `//` away, and the kernel follows any folder link on the way, so
    two different names can reach the same kept copy."""
    unlinked = (_unlinkable_identity(plugin_dir / member) for member in deployed_members)
    return {identity for identity in unlinked if identity is not None}


def _unlinkable_identity(member_path: Path) -> _InodeIdentity | None:
    in_the_way = entry_the_write_unlinks(member_path)
    if in_the_way is None:
        return None
    return in_the_way.st_dev, in_the_way.st_ino


def _backed_on_disk(plugin_dir: Path, entry: dict, replaced: set[_InodeIdentity]) -> bool:
    """A copy the write replaces is not where the update leaves the file, so it cannot vouch for
    it. A copy behind a folder link vouches for nothing either: `own_file_sha256` never follows
    one."""
    replaced_on_its_way = _unlinkable_identity(plugin_dir / entry["path"]) in replaced
    return not replaced_on_its_way and _held_as_signed(plugin_dir, entry)


def _held_as_signed(plugin_dir: Path, entry: dict) -> bool:
    signed_sha256: object = entry.get("sha256")
    return signed_sha256 is not None and own_file_sha256(plugin_dir, entry["path"]) == signed_sha256
