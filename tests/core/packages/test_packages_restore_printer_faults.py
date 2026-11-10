# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A fault of the printer's own while a restore zip is read is never blamed on the zip. Once the
zip's directory has passed its checks, no OSError, ValueError or RuntimeError is taken for damage,
and an OSError ZipFile hides behind a BadZipFile is raised as the fault it is."""

import errno
import io
import zipfile
from functools import partial
from pathlib import Path
from typing import NoReturn

import pytest

from core.packages import damaged_zip
from core.packages.damaged_zip import opened_restore_zip
from tests.core.packages.fake_changed_plugin import (
    CHANGED_SETTINGS,
    SETTINGS,
    SIGNED_SETTINGS,
    installed,
    restore_from,
    zip_of,
)

_FLASH_READ_FAULT = OSError(errno.EIO, "Input/output error")
_FAULTS_OF_THE_PRINTERS_OWN = [
    pytest.param(_FLASH_READ_FAULT, id="flash read"),
    pytest.param(OSError(errno.EINVAL, "Invalid argument"), id="seek refused"),
    pytest.param(OSError("no errno"), id="no errno"),
    pytest.param(ValueError("seek of closed file"), id="closed file"),
    pytest.param(RuntimeError("a fault of the daemon's own"), id="daemon"),
]


class _FlashThatFailsToRead(io.BytesIO):
    def read(self, size: int | None = -1) -> NoReturn:
        raise _FLASH_READ_FAULT


def _raise_the(fault: Exception, *_called_with: object) -> NoReturn:
    raise fault


def test_a_flash_fault_reading_the_directory_is_not_a_bad_zip() -> None:
    """ZipFile turns it into a BadZipFile; the OSError behind it is the printer's."""
    with pytest.raises(OSError, match="Input/output error"):
        opened_restore_zip(_FlashThatFailsToRead())


@pytest.mark.parametrize("fault", _FAULTS_OF_THE_PRINTERS_OWN)
def test_a_fault_opening_a_member_is_not_a_bad_zip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: Exception,
) -> None:
    plugin_dir = installed(tmp_path)
    archive_path = zip_of(tmp_path, {SETTINGS: SIGNED_SETTINGS})
    monkeypatch.setattr(zipfile.ZipFile, "open", partial(_raise_the, fault))

    with pytest.raises(type(fault)) as raised:
        restore_from(plugin_dir, archive_path)

    assert raised.value is fault
    assert (plugin_dir / SETTINGS).read_bytes() == CHANGED_SETTINGS


@pytest.mark.parametrize("fault", _FAULTS_OF_THE_PRINTERS_OWN)
def test_a_fault_while_hashing_a_member_is_not_a_bad_zip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: Exception,
) -> None:
    plugin_dir = installed(tmp_path)
    archive_path = zip_of(tmp_path, {SETTINGS: SIGNED_SETTINGS})
    monkeypatch.setattr(damaged_zip, "sha256_of_stream", partial(_raise_the, fault))

    with pytest.raises(type(fault)) as raised:
        restore_from(plugin_dir, archive_path)

    assert raised.value is fault
    assert (plugin_dir / SETTINGS).read_bytes() == CHANGED_SETTINGS
