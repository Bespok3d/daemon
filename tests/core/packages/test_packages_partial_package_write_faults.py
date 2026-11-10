# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A partial package the printer cannot write is refused the way a full one is: as a package that
does not fit, or one that did not unpack, never as a printer fault, and never after reading every
kept file for a package that cannot fit anyway."""

import json
import zipfile
from pathlib import Path

import pytest

from core.packages import archive, unpacked_size
from tests.core.packages.fake_partial_package import (
    CHANGED,
    KEPT_BYTES,
    entry,
    installed,
    manifest,
    partial_package,
)

# One name part past the 255 bytes a Linux or macOS filesystem takes.
_NAME_TOO_LONG = "files/" + "n" * 300
_LONG_NAMED_BYTES = b"a file the disk cannot name"


def _no_free_space(_destination: Path) -> int:
    return 0


def _package_with_a_name_too_long(tmp_path: Path) -> Path:
    long_named_manifest = manifest("2.0")
    long_named_manifest["files"].append(entry(_NAME_TOO_LONG, _LONG_NAMED_BYTES))
    package_path = tmp_path / "long-name.b3"
    with zipfile.ZipFile(package_path, "w") as package:
        package.writestr("manifest.json", json.dumps(long_named_manifest))
        package.writestr(CHANGED, "v2.0\n")
        package.writestr(_NAME_TOO_LONG, _LONG_NAMED_BYTES)
    return package_path


def test_a_partial_package_that_does_not_fit_is_refused_before_a_kept_file_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The kept file differs, so reading it first would have answered missing instead."""
    monkeypatch.setattr(unpacked_size, "free_space", _no_free_space)
    plugin_dir = installed(tmp_path, b"a binary someone changed")

    with pytest.raises(ValueError, match="MB free"):
        archive.unpack_package(tmp_path, partial_package(tmp_path, "2.0"))

    assert (plugin_dir / CHANGED).read_text() == "v1.0\n"


def test_a_name_too_long_for_the_disk_is_a_package_that_did_not_unpack(tmp_path: Path) -> None:
    installed(tmp_path, KEPT_BYTES)

    with pytest.raises(ValueError, match="did not unpack"):
        archive.unpack_package(tmp_path, _package_with_a_name_too_long(tmp_path))
