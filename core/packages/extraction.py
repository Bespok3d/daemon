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

from .baseline import STOCK_COPIES_DIR, stock_copies


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
    applied.

    The stock originals are the one thing kept back. When they are there, this package was unpacked
    over a version already on the printer, and they are the only copy of the files that version
    patched: taken away with the rest, the printer loses its way back to stock for good. A first
    install has none, so its refusal still leaves nothing behind."""
    if not stock_copies(plugin_dir).is_dir():
        shutil.rmtree(plugin_dir, ignore_errors=True)
        return
    for written in plugin_dir.iterdir():
        _discard_one(written)


def discard_if_first_install(plugin_dir: Path, replacing_an_install: bool) -> None:
    """Take a failed FIRST install back off the printer, once it has been switched off.

    A first install that failed was never an install. Left on disk it is reported as a plugin at
    its version with a deactivated marker, which reads as a plugin the printer has and could switch
    back on. There is nothing to switch back on: it never applied, and reactivating it only fails
    the same way again.

    Its kept originals go with it. Switching the plugin off wrote them back over every file it
    patched first, so by the time this runs those files are already what they were before the
    plugin arrived and no copy of them is owed to the printer.

    A version that replaced one already on the printer keeps its whole directory: that copy of the
    older version is the only way back to stock, and the user still has a working plugin to switch
    back on."""
    if replacing_an_install:
        return
    shutil.rmtree(plugin_dir, ignore_errors=True)


def _discard_one(written: Path) -> None:
    if written.name == STOCK_COPIES_DIR:
        return
    if written.is_dir() and not written.is_symlink():
        shutil.rmtree(written, ignore_errors=True)
        return
    written.unlink(missing_ok=True)


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
