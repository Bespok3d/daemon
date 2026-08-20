# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rewriting what a package's central directory SAYS its members unpack to.

The printer refuses a package that would not fit before it writes a byte, and it decides that from
the sizes the archive declares. A probe for that refusal therefore declares far more than the flash
holds while carrying almost nothing: a package that really held those bytes would fill the printer
if the refusal ever regressed, which is the one outcome a test on a bench machine must not have.

Only the central directory is rewritten, because that is where the daemon reads a member's unpacked
size from. manifest.json is left alone: the daemon reads it out of the archive before it measures
anything, and a manifest declaring gigabytes it does not hold could not be read at all.
"""
import struct

CENTRAL_DIRECTORY_ENTRY = b"PK\x01\x02"
END_OF_CENTRAL_DIRECTORY = b"PK\x05\x06"
CENTRAL_DIRECTORY_START_FIELD = 16
UNPACKED_SIZE_FIELD = 24
NAME_LENGTH_FIELD = 28
NAME_FIELD = 46


def _central_directory_start(package: bytes) -> int:
    end_record = package.rfind(END_OF_CENTRAL_DIRECTORY)
    return int(
        struct.unpack_from("<I", package, end_record + CENTRAL_DIRECTORY_START_FIELD)[0],
    )


def unpacked_sizes_declared_as(package: bytes, declared_size: int, left_alone: set[str]) -> bytes:
    """`package` with every member outside `left_alone` claiming to unpack to `declared_size`."""
    rewritten = bytearray(package)
    entry = _central_directory_start(package)
    while rewritten[entry:entry + len(CENTRAL_DIRECTORY_ENTRY)] == CENTRAL_DIRECTORY_ENTRY:
        name_length, extra_length, comment_length = struct.unpack_from(
            "<HHH", rewritten, entry + NAME_LENGTH_FIELD,
        )
        name = rewritten[entry + NAME_FIELD:entry + NAME_FIELD + name_length].decode()
        if name not in left_alone:
            struct.pack_into("<I", rewritten, entry + UNPACKED_SIZE_FIELD, declared_size)
        entry += NAME_FIELD + name_length + extra_length + comment_length
    return bytes(rewritten)
