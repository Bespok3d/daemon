# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A restore zip the printer will not unpack is a fault in what was sent, refused before any file
is written."""

import zipfile
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
from tests.core.packages.zip_layout import CENTRAL_DIRECTORY_SIGNATURE, CENTRAL_FLAG_OFFSET

_ENCRYPTED_FLAG = 0x01


def test_a_file_that_is_not_a_zip_is_a_bad_request(tmp_path: Path) -> None:
    archive_path = tmp_path / "restore.zip"
    archive_path.write_bytes(b"not a zip")

    with pytest.raises(DamagedRestoreArchiveError, match="did not unpack"):
        restore_from(installed(tmp_path), archive_path)


def _signed_settings_packed_with(tmp_path: Path, packing_method: int) -> Path:
    archive_path = tmp_path / "restore.zip"
    with zipfile.ZipFile(archive_path, "w", packing_method) as restore_zip:
        restore_zip.writestr(SETTINGS, SIGNED_SETTINGS)
    return archive_path


@pytest.mark.parametrize(
    "packing_method", [zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA], ids=["bz2", "lzma"],
)
def test_a_member_packed_with_no_cap_on_its_unpacked_size_is_refused_unread(
    tmp_path: Path, packing_method: int,
) -> None:
    """bz2 and lzma unpack a whole read at once, so a small member could fill the memory."""
    plugin_dir = installed(tmp_path)

    with pytest.raises(DamagedRestoreArchiveError, match="not stored or deflated"):
        restore_from(plugin_dir, _signed_settings_packed_with(tmp_path, packing_method))

    assert (plugin_dir / SETTINGS).read_bytes() == CHANGED_SETTINGS


def _signed_settings_marked_encrypted(tmp_path: Path) -> Path:
    archive_path = zip_of(tmp_path, {SETTINGS: SIGNED_SETTINGS})
    marked = bytearray(archive_path.read_bytes())
    marked[marked.index(CENTRAL_DIRECTORY_SIGNATURE) + CENTRAL_FLAG_OFFSET] |= _ENCRYPTED_FLAG
    archive_path.write_bytes(bytes(marked))
    return archive_path


def test_an_encrypted_member_is_a_bad_zip(tmp_path: Path) -> None:
    plugin_dir = installed(tmp_path)

    with pytest.raises(DamagedRestoreArchiveError, match="encrypted"):
        restore_from(plugin_dir, _signed_settings_marked_encrypted(tmp_path))

    assert (plugin_dir / SETTINGS).read_bytes() == CHANGED_SETTINGS
