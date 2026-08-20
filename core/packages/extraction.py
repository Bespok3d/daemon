# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Writing a package's members onto the printer, and taking them back off when one fails.

A .b3 is untrusted input from the internet. Its size checks all read what the archive DECLARES, so
a member whose compressed stream disagrees with its declaration only fails once it is being
written, and the flash can fill up mid-write regardless of what the package declared. Either way
extraction stops part written, and a part written plugin left on disk would make the daemon report
a plugin it never installed.
"""

import shutil
import zipfile
from pathlib import Path


def extract_or_discard(
    zf: zipfile.ZipFile, plugin_dir: Path, members: list[str], replacing_an_install: bool,
) -> None:
    """A first install that fails part way through has its extraction taken back off the printer.
    A version replacing one already on the printer keeps its directory, because that directory is
    also where the older version's stock originals and settings live: deleting it would take the
    only copy of the files the printer needs to get back to stock."""
    try:
        _write_members(zf, plugin_dir, members)
    except (zipfile.BadZipFile, OSError) as damage:
        if not replacing_an_install:
            discard_extraction(plugin_dir)
        raise ValueError(f"the package did not unpack: {damage}") from damage


def discard_extraction(plugin_dir: Path) -> None:
    """Take back what unpacking wrote. A package the printer refuses after it was unpacked must not
    leave its files behind: kept, the tree would make /capabilities report a plugin the daemon never
    applied."""
    shutil.rmtree(plugin_dir, ignore_errors=True)


def _write_members(zf: zipfile.ZipFile, plugin_dir: Path, members: list[str]) -> None:
    # Unlink an existing file before extracting over it. Overwriting a running binary in place fails
    # with ETXTBSY ("Text file busy"); unlinking keeps the running process's inode and writes a new
    # file, so a reinstall or version switch can replace a binary that is currently executing. The
    # delete runs as root, which is why the caller refuses an escaping member before the plugin dir
    # is ever created.
    for name in members:
        dest = plugin_dir / name
        if dest.is_file() or dest.is_symlink():
            dest.unlink()
        zf.extract(name, plugin_dir)
