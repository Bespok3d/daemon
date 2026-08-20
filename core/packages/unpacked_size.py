# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a package would occupy once unpacked, weighed against the space the printer actually has.

A .b3 is a zip, and a zip declares each member's unpacked size in its own directory, so the total is
known before a byte is written. Extraction writes at most that declared size per member, which is
what makes the number safe to trust: a package that claims to be small cannot then write large.

The printer's storage is shared with Klipper, Moonraker and the user's own files, and a full disk
takes the printer down with it. So the check keeps a reserve free rather than allowing the very last
byte, and it runs before the plugin directory is created: a package too big is refused with the disk
untouched, instead of filling it and leaving a half written tree behind.
"""

import shutil
import zipfile
from pathlib import Path

FREE_SPACE_RESERVE_BYTES = 32 * 1024 * 1024
MEGABYTE = 1024 * 1024


def unpacked_size(archive: zipfile.ZipFile, members: list[str]) -> int:
    """The bytes the named members occupy once written out, as the archive itself declares them."""
    return sum(archive.getinfo(name).file_size for name in members)


def free_space(destination: Path) -> int:
    """Free bytes on the filesystem holding `destination`, which need not exist yet: on a first
    install the plugin root is created by the install itself, so the nearest existing parent is what
    carries the answer."""
    mounted = next(path for path in (destination, *destination.parents) if path.exists())
    return shutil.disk_usage(mounted).free


def refuse_package_that_does_not_fit(
    archive: zipfile.ZipFile, plugin_root: Path, members: list[str],
) -> None:
    """Raise before extraction unless the package fits with the reserve still free."""
    needed = unpacked_size(archive, members)
    available = free_space(plugin_root)
    if needed + FREE_SPACE_RESERVE_BYTES <= available:
        return
    raise ValueError(
        f"package needs {needed // MEGABYTE} MB unpacked and the printer has "
        f"{available // MEGABYTE} MB free; it is refused so the printer keeps working space",
    )
