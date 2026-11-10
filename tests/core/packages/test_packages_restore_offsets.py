# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A restore zip whose directory gives a version or an offset no zip can hold is a fault in what
was sent. ZipFile raises neither as a BadZipFile: a version above the newest it reads is a
NotImplementedError, and a header offset before the start of the file or past any seek would fail
its seek with the same error a fault of the printer's own raises, so it is refused from the
directory first."""

import struct
from collections.abc import Callable
from pathlib import Path

import pytest

from core.packages.damaged_zip import DamagedRestoreArchiveError
from tests.core.packages.fake_changed_plugin import (
    CHANGED_SETTINGS,
    SETTINGS,
    SIGNED_SETTINGS,
    installed,
    restore_from,
    zip_of,
)
from tests.core.packages.zip_layout import (
    CENTRAL_DIRECTORY_SIGNATURE,
    CENTRAL_EXTRA_LENGTH_OFFSET,
    CENTRAL_EXTRACT_VERSION_OFFSET,
    CENTRAL_HEADER_OFFSET_OFFSET,
    CENTRAL_NAME_OFFSET,
    END_RECORD_DIRECTORY_OFFSET_OFFSET,
    END_RECORD_DIRECTORY_SIZE_OFFSET,
    END_RECORD_SIGNATURE,
)

# 6.3 is the newest zip version ZipFile reads, written as 63.
_NEWER_THAN_ANY_READABLE_VERSION = 64
_ZIP64_EXTRA_TAG = 0x0001
_ZIP64_HEADER_OFFSET_SIZE = 8
# The value that tells ZipFile to take the member's header offset from its zip64 extra field.
_OFFSET_IN_ZIP64_EXTRA = 0xFFFF_FFFF
_PAST_ANY_SEEKABLE_OFFSET = 2**63


def _restore_zip_bytes(tmp_path: Path) -> tuple[Path, bytearray]:
    archive_path = zip_of(tmp_path, {SETTINGS: SIGNED_SETTINGS})
    return archive_path, bytearray(archive_path.read_bytes())


def _add_to_field(zip_bytes: bytearray, field_offset: int, field_format: str, amount: int) -> None:
    field_value = struct.unpack_from(field_format, zip_bytes, field_offset)[0]
    struct.pack_into(field_format, zip_bytes, field_offset, field_value + amount)


def _with_a_newer_version(tmp_path: Path) -> Path:
    archive_path, zip_bytes = _restore_zip_bytes(tmp_path)
    directory_start = zip_bytes.index(CENTRAL_DIRECTORY_SIGNATURE)
    zip_bytes[directory_start + CENTRAL_EXTRACT_VERSION_OFFSET] = _NEWER_THAN_ANY_READABLE_VERSION
    archive_path.write_bytes(bytes(zip_bytes))
    return archive_path


def _with_the_directory_one_byte_further_on(tmp_path: Path) -> Path:
    """ZipFile takes the gap for bytes put before the zip, so the member's header lands one byte
    before the start of the file."""
    archive_path, zip_bytes = _restore_zip_bytes(tmp_path)
    offset_field = zip_bytes.rindex(END_RECORD_SIGNATURE) + END_RECORD_DIRECTORY_OFFSET_OFFSET
    _add_to_field(zip_bytes, offset_field, "<I", 1)
    archive_path.write_bytes(bytes(zip_bytes))
    return archive_path


def _with_a_zip64_header_offset_past_any_seek(tmp_path: Path) -> Path:
    archive_path, zip_bytes = _restore_zip_bytes(tmp_path)
    directory_start = zip_bytes.index(CENTRAL_DIRECTORY_SIGNATURE)
    zip64_extra = struct.pack(
        "<HHQ", _ZIP64_EXTRA_TAG, _ZIP64_HEADER_OFFSET_SIZE, _PAST_ANY_SEEKABLE_OFFSET)
    struct.pack_into(
        "<I", zip_bytes, directory_start + CENTRAL_HEADER_OFFSET_OFFSET, _OFFSET_IN_ZIP64_EXTRA)
    _add_to_field(zip_bytes, directory_start + CENTRAL_EXTRA_LENGTH_OFFSET, "<H", len(zip64_extra))
    extra_start = directory_start + CENTRAL_NAME_OFFSET + len(SETTINGS)
    zip_bytes[extra_start:extra_start] = zip64_extra
    size_field = zip_bytes.rindex(END_RECORD_SIGNATURE) + END_RECORD_DIRECTORY_SIZE_OFFSET
    _add_to_field(zip_bytes, size_field, "<I", len(zip64_extra))
    archive_path.write_bytes(bytes(zip_bytes))
    return archive_path


@pytest.mark.parametrize(
    "broken_zip",
    [
        _with_a_newer_version,
        _with_the_directory_one_byte_further_on,
        _with_a_zip64_header_offset_past_any_seek,
    ],
)
def test_a_directory_no_zip_can_hold_is_a_bad_zip(
    tmp_path: Path, broken_zip: Callable[[Path], Path],
) -> None:
    plugin_dir = installed(tmp_path)
    archive_path = broken_zip(tmp_path)

    with pytest.raises(DamagedRestoreArchiveError, match="did not unpack"):
        restore_from(plugin_dir, archive_path)

    assert (plugin_dir / SETTINGS).read_bytes() == CHANGED_SETTINGS
