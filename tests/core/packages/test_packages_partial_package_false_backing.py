# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A left-out file whose copy on disk holds the signed bytes and still vouches for nothing: the
copy is not the plugin's own, or the package would replace it with something else."""

import json
import os
import zipfile
from pathlib import Path

import pytest

from core.packages import archive
from core.packages.integrity import MISSING_MEMBER, IntegrityError
from tests.core.packages.fake_partial_package import (
    CHANGED,
    KEPT,
    KEPT_BYTES,
    installed,
    manifest,
    partial_package,
)


def test_a_left_out_file_with_a_second_hard_link_vouches_for_nothing(tmp_path: Path) -> None:
    """A second link shares the kept copy's inode with another path, maybe a file outside the plugin
    dir, and the chown that ends the update would hand that file to the plugin's user."""
    plugin_dir = installed(tmp_path, KEPT_BYTES)
    os.link(plugin_dir / KEPT, plugin_dir / "files/second-link.bin")

    with pytest.raises(IntegrityError) as refusal:
        archive.unpack_package(tmp_path, partial_package(tmp_path, "2.0"))

    assert (refusal.value.reason, refusal.value.paths) == (MISSING_MEMBER, [KEPT])
    assert (plugin_dir / CHANGED).read_text() == "v1.0\n"


def _package_with_a_dir_entry(tmp_path: Path, dir_entry: str) -> Path:
    package_path = tmp_path / "dir-entry.b3"
    with zipfile.ZipFile(package_path, "w") as package:
        package.writestr("manifest.json", json.dumps(manifest("2.0")))
        package.writestr(CHANGED, "v2.0\n")
        package.mkdir(dir_entry)
    return package_path


def test_a_dir_entry_at_a_left_out_path_refuses_the_update_before_a_byte_is_written(
    tmp_path: Path,
) -> None:
    """Extracting that entry unlinks the kept copy to make a dir in its place, so the copy cannot
    vouch for the file the update leaves there."""
    plugin_dir = installed(tmp_path, KEPT_BYTES)

    with pytest.raises(IntegrityError) as refusal:
        archive.unpack_package(tmp_path, _package_with_a_dir_entry(tmp_path, KEPT))

    assert (refusal.value.reason, refusal.value.paths) == (MISSING_MEMBER, [KEPT])
    assert (plugin_dir / KEPT).read_bytes() == KEPT_BYTES


@pytest.mark.parametrize("spelled_otherwise", [f"./{KEPT}/", KEPT.replace("/", "//") + "/"])
def test_a_dir_entry_spelled_otherwise_at_a_left_out_path_refuses_the_update(
    tmp_path: Path, spelled_otherwise: str,
) -> None:
    """The write joins the name with pathlib, which tidies it back to the kept copy's own path."""
    plugin_dir = installed(tmp_path, KEPT_BYTES)

    with pytest.raises(IntegrityError) as refusal:
        archive.unpack_package(tmp_path, _package_with_a_dir_entry(tmp_path, spelled_otherwise))

    assert (refusal.value.reason, refusal.value.paths) == (MISSING_MEMBER, [KEPT])
    assert (plugin_dir / KEPT).read_bytes() == KEPT_BYTES


def test_a_left_out_file_behind_a_folder_link_refuses_the_update_and_keeps_the_link(
    tmp_path: Path,
) -> None:
    """The copy is read without following the folder link, so it vouches for nothing, and the
    refusal comes before the dir entry would unlink that link to make an empty dir."""
    plugin_dir = installed(tmp_path, KEPT_BYTES)
    (plugin_dir / "files").rename(plugin_dir / "store")
    (plugin_dir / "files").symlink_to(plugin_dir / "store")

    with pytest.raises(IntegrityError) as refusal:
        archive.unpack_package(tmp_path, _package_with_a_dir_entry(tmp_path, "files/"))

    assert (refusal.value.reason, refusal.value.paths) == (MISSING_MEMBER, [KEPT])
    assert (plugin_dir / "files").is_symlink()
