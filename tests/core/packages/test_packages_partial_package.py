# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A package may leave out the listed files the printer already holds exactly as signed.

The manifest still lists every file with its sha256, so the copy on disk vouches for a left-out
file only when it holds those exact bytes. Anything else refuses the whole package before a byte
is written, so the install on the printer stays as it was.
"""

import json
import zipfile
from io import BufferedReader
from pathlib import Path

import pytest

from core.packages import archive, own_file
from core.packages.integrity import MISSING_MEMBER, IntegrityError
from tests.core.packages.fake_partial_package import (
    CHANGED,
    KEPT,
    KEPT_BYTES,
    PLUGIN,
    entry,
    installed,
    manifest,
    partial_package,
)


def _unreadable(kept_stream: BufferedReader) -> str:
    raise PermissionError(f"cannot read {kept_stream.name}")


def test_an_update_may_leave_out_a_file_the_printer_holds_as_signed(tmp_path: Path) -> None:
    plugin_dir = installed(tmp_path, KEPT_BYTES)

    _manifest_read, _dir, file_count, replacing = archive.unpack_package(
        tmp_path, partial_package(tmp_path, "2.0"))

    assert (plugin_dir / CHANGED).read_text() == "v2.0\n"
    assert (plugin_dir / KEPT).read_bytes() == KEPT_BYTES
    assert (plugin_dir / "user_vars.json").read_text() == '{"port": "7912"}'
    assert (file_count, replacing) == (2, True)


def test_a_left_out_file_that_differs_refuses_the_update_before_a_byte_is_written(
    tmp_path: Path,
) -> None:
    plugin_dir = installed(tmp_path, b"a binary someone changed")

    with pytest.raises(IntegrityError) as refusal:
        archive.unpack_package(tmp_path, partial_package(tmp_path, "2.0"))

    assert (refusal.value.reason, refusal.value.paths) == (MISSING_MEMBER, [KEPT])
    assert (plugin_dir / CHANGED).read_text() == "v1.0\n"


def test_a_left_out_file_that_is_gone_refuses_the_update(tmp_path: Path) -> None:
    plugin_dir = installed(tmp_path, KEPT_BYTES)
    (plugin_dir / KEPT).unlink()

    with pytest.raises(IntegrityError) as refusal:
        archive.unpack_package(tmp_path, partial_package(tmp_path, "2.0"))

    assert (refusal.value.reason, refusal.value.paths) == (MISSING_MEMBER, [KEPT])
    assert (plugin_dir / CHANGED).read_text() == "v1.0\n"


def test_a_left_out_file_held_through_a_symlink_vouches_for_nothing(tmp_path: Path) -> None:
    """Matching bytes behind a link are some other file's bytes, not the listed file's own copy.
    A link out of the plugin dir is already refused as escaping; this one stays inside it."""
    plugin_dir = installed(tmp_path, KEPT_BYTES)
    (plugin_dir / KEPT).rename(plugin_dir / "files/copy.bin")
    (plugin_dir / KEPT).symlink_to(plugin_dir / "files/copy.bin")

    with pytest.raises(IntegrityError) as refusal:
        archive.unpack_package(tmp_path, partial_package(tmp_path, "2.0"))

    assert (refusal.value.reason, refusal.value.paths) == (MISSING_MEMBER, [KEPT])
    assert (plugin_dir / CHANGED).read_text() == "v1.0\n"


def test_a_first_install_cannot_leave_out_a_kept_file(tmp_path: Path) -> None:
    plugin_root = tmp_path / "plugins"

    with pytest.raises(IntegrityError) as refusal:
        archive.unpack_package(plugin_root, partial_package(tmp_path, "1.0"))

    assert (refusal.value.reason, refusal.value.paths) == (MISSING_MEMBER, [KEPT])
    assert not (plugin_root / PLUGIN).exists()


def test_a_left_out_file_the_packer_never_hashed_refuses_the_update(tmp_path: Path) -> None:
    unhashed_files = [{"path": KEPT}, entry(CHANGED, b"v2.0\n")]
    unhashed_manifest = {**manifest("2.0"), "files": unhashed_files}
    package_path = tmp_path / "unhashed.b3"
    with zipfile.ZipFile(package_path, "w") as package:
        package.writestr("manifest.json", json.dumps(unhashed_manifest))
        package.writestr(CHANGED, "v2.0\n")
    plugin_dir = installed(tmp_path, KEPT_BYTES)

    with pytest.raises(IntegrityError) as refusal:
        archive.unpack_package(tmp_path, package_path)

    assert (refusal.value.reason, refusal.value.paths) == (MISSING_MEMBER, [KEPT])
    assert (plugin_dir / CHANGED).read_text() == "v1.0\n"


def test_a_left_out_file_the_disk_cannot_read_refuses_the_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin_dir = installed(tmp_path, KEPT_BYTES)
    monkeypatch.setattr(own_file, "sha256_of_stream", _unreadable)

    with pytest.raises(IntegrityError) as refusal:
        archive.unpack_package(tmp_path, partial_package(tmp_path, "2.0"))

    assert (refusal.value.reason, refusal.value.paths) == (MISSING_MEMBER, [KEPT])
    assert (plugin_dir / CHANGED).read_text() == "v1.0\n"
