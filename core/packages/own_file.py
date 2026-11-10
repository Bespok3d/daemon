# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The sha256 of a file the plugin dir holds as a plain file of its own, and of nothing else.

A symlink, a second hard link, or a folder link on the way may lead to any file on the printer, so
its bytes vouch for nothing the plugin shipped, and the root daemon must not read it for the
plugin's user. That user owns the tree and can swap a file or a folder for a link at any moment, so
each folder on the way and the file itself are opened by descriptor without following a link, and
the file is checked on the descriptor that is then read, never on the path ahead of the read. A
`..` would step back out of a folder opened that way, so a path with one is never the plugin's own.
"""

import functools
import os
import stat
from pathlib import Path, PurePosixPath

from .integrity import sha256_of_stream
from .members import walks_only_down

# The plugin dir sits in the root-owned plugin root, so only what is inside it can be swapped.
_PLUGIN_DIR_OPEN_FLAGS = os.O_RDONLY | os.O_DIRECTORY
_FOLDER_OPEN_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
# O_NONBLOCK so a fifo swapped in at the path cannot hang the root daemon on its open.
_OWN_FILE_OPEN_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK


def own_file_sha256(plugin_dir: Path, path: str) -> str | None:
    """None when `path` is not the plugin's own regular file, or one the disk cannot read back. It
    is taken as missing, so the app offers it back and an update that left it out is refused as
    missing, instead of either failing whole on an unexplained read error."""
    path_parts = PurePosixPath(path).parts
    if not path_parts or not walks_only_down(path):
        return None
    try:
        return _sha256_if_own(_open_without_following(plugin_dir, path_parts))
    except OSError:
        return None


def _open_without_following(plugin_dir: Path, path_parts: tuple[str, ...]) -> int:
    *folder_names, file_name = path_parts
    plugin_folder = os.open(plugin_dir, _PLUGIN_DIR_OPEN_FLAGS)
    kept_folder = functools.reduce(_open_in, folder_names, plugin_folder)
    return _open_in(kept_folder, file_name, _OWN_FILE_OPEN_FLAGS)


def _open_in(folder: int, entry_name: str, open_flags: int = _FOLDER_OPEN_FLAGS) -> int:
    """Open one entry of an open folder, and close the folder whether the open worked or not."""
    try:
        return os.open(entry_name, open_flags, dir_fd=folder)
    finally:
        os.close(folder)


def _sha256_if_own(descriptor: int) -> str | None:
    try:
        return _sha256_of_regular_file(descriptor)
    finally:
        os.close(descriptor)


def _sha256_of_regular_file(descriptor: int) -> str | None:
    """Checked before the descriptor is wrapped: wrapping a folder's descriptor fails, and the
    failed wrap does not close it."""
    opened = os.fstat(descriptor)
    if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
        return None
    with open(descriptor, "rb", closefd=False) as kept_stream:
        return sha256_of_stream(kept_stream)
