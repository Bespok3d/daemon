# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reading the zip of files sent to put back, telling a fault in its bytes from one of the printer.

ZipFile raises no single error for a damaged zip, and some of what it raises (a BadZipFile, an
OSError) is also how a read fault of the printer's flash shows. So every member is first checked
from the zip's directory for what would make it fail the way a printer fault fails, and then each
step of the read maps only the errors that step raises for damage, and nothing else is blamed on
the zip.
"""

import errno
import io
import sys
import zipfile
import zlib
from typing import BinaryIO, cast

from .integrity import sha256_of_stream

# What reading the zip's directory raises for damage: a version newer than ZipFile reads is a
# NotImplementedError, and a name flagged as UTF-8 that does not decode a UnicodeDecodeError.
_DAMAGED_DIRECTORY_ERRORS = (zipfile.BadZipFile, NotImplementedError, UnicodeDecodeError)
# What opening a member that passed the directory check raises for damage: its own header.
_DAMAGED_HEADER_ERRORS = (zipfile.BadZipFile, UnicodeDecodeError)
# What reading a member's bytes raises for damage: a wrong CRC, deflate failing, an early end.
_DAMAGED_MEMBER_ERRORS = (zipfile.BadZipFile, zlib.error, EOFError)
# bz2 and lzma unpack a whole read at once with no cap on its size, so a small member could fill
# the printer's memory; the app packs with deflate.
_METHODS_THE_PRINTER_UNPACKS = (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
# Flag bits 0, 5 and 6 (APPNOTE 4.4.4): encrypted, patched, strongly encrypted.
_FLAGS_THE_PRINTER_DOES_NOT_READ = 0x01 | 0x20 | 0x40
_ZIP_DIRECTORY = "its directory"


class DamagedRestoreArchiveError(Exception):
    """The uploaded zip does not unpack, so the fault is in what was sent, not on the printer."""


def opened_restore_zip(restore_archive: BinaryIO) -> zipfile.ZipFile:
    archive_size = restore_archive.seek(0, io.SEEK_END)
    restore_zip = _read_directory(restore_archive)
    unreadable = _first_unreadable_member(restore_zip.infolist(), archive_size)
    if unreadable is None:
        return restore_zip
    restore_zip.close()
    raise _damaged(_ZIP_DIRECTORY, unreadable)


def member_sha256(restore_zip: zipfile.ZipFile, name: str) -> str:
    with _opened_member(restore_zip, name) as member_stream:
        return _sha256_of_member(name, member_stream)


def _read_directory(restore_archive: BinaryIO) -> zipfile.ZipFile:
    callers_own_fault = sys.exception()
    try:
        return zipfile.ZipFile(restore_archive)
    except _DAMAGED_DIRECTORY_ERRORS as damage:
        _raise_the_read_fault_behind(damage, callers_own_fault)
        raise _damaged(_ZIP_DIRECTORY, damage) from damage


def _raise_the_read_fault_behind(
    damage: Exception, callers_own_fault: BaseException | None,
) -> None:
    """ZipFile turns any OSError reading the zip's end record into a BadZipFile, so that OSError is
    its context. Only EINVAL there is the zip's own: a seek before the start of a file too short for
    the record it claims. A context that is the fault the caller was handling came from no read."""
    read_fault = damage.__context__
    if read_fault is callers_own_fault or not isinstance(read_fault, OSError):
        return
    if read_fault.errno != errno.EINVAL:
        raise read_fault from None


def _first_unreadable_member(members: list[zipfile.ZipInfo], archive_size: int) -> str | None:
    unreadable = (
        f"{member.filename}: {reason}"
        for member in members
        if (reason := _why_unreadable(member, archive_size))
    )
    return next(unreadable, None)


def _why_unreadable(member: zipfile.ZipInfo, archive_size: int) -> str | None:
    """A header offset outside the zip fails its seek with an OSError, a ValueError or an
    OverflowError, whichever the upload's spool raises for it, and those are the errors a fault of
    the printer's own raises too, so it is refused here before any seek."""
    if member.compress_type not in _METHODS_THE_PRINTER_UNPACKS:
        return f"packed with method {member.compress_type}, not stored or deflated"
    if member.flag_bits & _FLAGS_THE_PRINTER_DOES_NOT_READ:
        return "encrypted or patched"
    if not 0 <= member.header_offset < archive_size:
        return "its header lies outside the zip"
    return None


def _opened_member(restore_zip: zipfile.ZipFile, name: str) -> zipfile.ZipExtFile:
    try:
        return cast(zipfile.ZipExtFile, restore_zip.open(name))
    except _DAMAGED_HEADER_ERRORS as damage:
        raise _damaged(name, damage) from damage


def _sha256_of_member(name: str, member_stream: zipfile.ZipExtFile) -> str:
    try:
        return sha256_of_stream(member_stream)
    except _DAMAGED_MEMBER_ERRORS as damage:
        raise _damaged(name, damage) from damage


def _damaged(where: str, damage: object) -> DamagedRestoreArchiveError:
    return DamagedRestoreArchiveError(f"the restore archive did not unpack: {where}: {damage}")
