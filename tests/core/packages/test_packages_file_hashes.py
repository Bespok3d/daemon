# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The hashes of the files an installed plugin keeps on the printer, for the app to compare with the
signed manifest it holds. Only the files the manifest lists as kept on disk are named, and one the
plugin dir does not hold as its own regular file is named with no hash."""

import functools
import hashlib
import os
import shutil
from collections.abc import Callable
from io import BufferedReader
from pathlib import Path

import pytest

from core.packages import own_file
from core.packages.file_drift import file_hashes
from core.packages.integrity import sha256_of

_KEPT = "files/daemon.bin"
_MISSING = "files/gone.bin"
_LINKED = "files/linked.bin"
_RENDERED = "files/rendered.cfg"


def _entry(path: str) -> dict:
    return {"path": path, "sha256": "0" * 64, "mode": "644"}


_MANIFEST = {
    "name": "spoolman", "version": "1.0",
    "install": {"templates": [{"from": "files/rendered.cfg.tmpl", "to": _RENDERED}]},
    "files": [_entry(_KEPT), _entry(_MISSING), _entry(_LINKED), _entry(_RENDERED),
              _entry("doc/README.md")],
}


def _installed(tmp_path: Path) -> Path:
    plugin_dir = tmp_path / "spoolman"
    (plugin_dir / "files").mkdir(parents=True)
    (plugin_dir / "doc").mkdir()
    (plugin_dir / _KEPT).write_bytes(b"the binary on the printer")
    (plugin_dir / _RENDERED).write_text("port = 7912\n")
    (plugin_dir / "doc/README.md").write_text("docs never deploy\n")
    (plugin_dir / "files/unlisted.sh").write_text("echo not in the manifest\n")
    (plugin_dir / "files/copy.bin").write_bytes(b"behind a link")
    (plugin_dir / _LINKED).symlink_to(plugin_dir / "files/copy.bin")
    return plugin_dir


_KEPT_SHA256 = hashlib.sha256(b"the binary on the printer").hexdigest()
_NONE_HELD = {_KEPT: None, _MISSING: None, _LINKED: None}


def test_only_the_listed_kept_files_are_named_and_only_regular_ones_hashed(tmp_path: Path) -> None:
    hashes = file_hashes(_installed(tmp_path), _MANIFEST)

    assert hashes == {**_NONE_HELD, _KEPT: _KEPT_SHA256}


def test_the_streamed_hash_is_the_files_sha256(tmp_path: Path) -> None:
    large_binary = tmp_path / "large.bin"
    content = bytes(range(256)) * 40_000
    large_binary.write_bytes(content)

    assert sha256_of(large_binary) == hashlib.sha256(content).hexdigest()


def test_a_files_entry_that_names_no_path_is_skipped_not_a_crash(tmp_path: Path) -> None:
    malformed = {**_MANIFEST, "files": ["files/daemon.bin", {"sha256": "0" * 64}, _entry(_KEPT)]}

    hashes = file_hashes(_installed(tmp_path), malformed)

    assert hashes == {_KEPT: _KEPT_SHA256}


def _vanished_while_read(kept_stream: BufferedReader) -> str:
    raise FileNotFoundError(f"No such file or directory: {kept_stream.name}")


def test_a_file_that_cannot_be_read_back_has_no_hash_like_a_missing_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plugin may replace one of its own files while it is read; the app then offers it back."""
    monkeypatch.setattr(own_file, "sha256_of_stream", _vanished_while_read)

    assert file_hashes(_installed(tmp_path), _MANIFEST) == _NONE_HELD


def _swapped_for_a_link_once_checked(outside_file: Path, plugin_dir: Path, path: str) -> bool:
    kept_file = plugin_dir / path
    kept_file.unlink(missing_ok=True)
    kept_file.symlink_to(outside_file)
    return True


def test_a_link_swapped_in_after_the_check_is_not_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The plugin's user owns its tree, so it can swap a file for a link to a root-only file
    between the check and the read; the root daemon must not hash what that link points at."""
    plugin_dir = _installed(tmp_path)
    root_only = tmp_path / "root-only.txt"
    root_only.write_text("a secret only root may read\n")
    swap = functools.partial(_swapped_for_a_link_once_checked, root_only, plugin_dir)
    monkeypatch.setattr(own_file, "walks_only_down", swap)

    assert file_hashes(plugin_dir, _MANIFEST) == _NONE_HELD


def _folder_swapped_for_a_link_once_checked(
    outside_folder: Path, plugin_dir: Path, _path: str,
) -> bool:
    kept_folder = plugin_dir / "files"
    if not kept_folder.is_symlink():
        shutil.rmtree(kept_folder)
        kept_folder.symlink_to(outside_folder)
    return True


def test_a_folder_swapped_for_a_link_after_the_check_is_not_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin_dir = _installed(tmp_path)
    outside_folder = tmp_path / "root-only"
    outside_folder.mkdir()
    (outside_folder / "daemon.bin").write_bytes(b"the binary on the printer")
    swap = functools.partial(_folder_swapped_for_a_link_once_checked, outside_folder, plugin_dir)
    monkeypatch.setattr(own_file, "walks_only_down", swap)

    assert file_hashes(plugin_dir, _MANIFEST) == _NONE_HELD


def _open_descriptor_count() -> int:
    return len(os.listdir("/dev/fd"))


@pytest.mark.parametrize("make_in_place", [Path.mkdir, os.mkfifo])
def test_a_folder_or_a_fifo_at_a_kept_path_has_no_hash_and_no_descriptor_left_open(
    tmp_path: Path, make_in_place: Callable[[Path], None],
) -> None:
    plugin_dir = _installed(tmp_path)
    (plugin_dir / _KEPT).unlink()
    make_in_place(plugin_dir / _KEPT)
    descriptors_before = _open_descriptor_count()

    hashes = file_hashes(plugin_dir, _MANIFEST)

    assert (hashes, _open_descriptor_count()) == (_NONE_HELD, descriptors_before)
