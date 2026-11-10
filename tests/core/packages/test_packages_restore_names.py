# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A restore zip whose file name claims UTF-8 but does not decode is a fault in what was sent.
ZipFile raises a UnicodeDecodeError for it, not a BadZipFile, both when it reads the zip's own
directory and when it opens a member and reads that member's own header."""

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
    CENTRAL_FLAG_OFFSET,
    CENTRAL_NAME_OFFSET,
    LOCAL_FLAG_OFFSET,
    LOCAL_HEADER_SIGNATURE,
    LOCAL_NAME_OFFSET,
)

# Bit 11 of the little-endian flags, so bit 3 of their second byte.
_UTF8_NAME_FLAG_HIGH_BYTE = 0x08
_NOT_UTF8 = 0xFF


def _signed_settings_with_a_broken_name(
    tmp_path: Path, header_signature: bytes, flag_offset: int, name_offset: int,
) -> Path:
    archive_path = zip_of(tmp_path, {SETTINGS: SIGNED_SETTINGS})
    broken = bytearray(archive_path.read_bytes())
    header_start = broken.index(header_signature)
    broken[header_start + flag_offset + 1] |= _UTF8_NAME_FLAG_HIGH_BYTE
    broken[header_start + name_offset] = _NOT_UTF8
    archive_path.write_bytes(bytes(broken))
    return archive_path


def test_a_name_in_the_zips_directory_that_does_not_decode_is_a_bad_zip(tmp_path: Path) -> None:
    plugin_dir = installed(tmp_path)
    archive_path = _signed_settings_with_a_broken_name(
        tmp_path, CENTRAL_DIRECTORY_SIGNATURE, CENTRAL_FLAG_OFFSET, CENTRAL_NAME_OFFSET)

    with pytest.raises(DamagedRestoreArchiveError, match="did not unpack"):
        restore_from(plugin_dir, archive_path)

    assert (plugin_dir / SETTINGS).read_bytes() == CHANGED_SETTINGS


def test_a_name_in_a_members_own_header_that_does_not_decode_is_a_bad_zip(
    tmp_path: Path,
) -> None:
    plugin_dir = installed(tmp_path)
    archive_path = _signed_settings_with_a_broken_name(
        tmp_path, LOCAL_HEADER_SIGNATURE, LOCAL_FLAG_OFFSET, LOCAL_NAME_OFFSET)

    with pytest.raises(DamagedRestoreArchiveError, match="did not unpack"):
        restore_from(plugin_dir, archive_path)

    assert (plugin_dir / SETTINGS).read_bytes() == CHANGED_SETTINGS
