# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A package-chosen name with a `..` is refused even when it resolves back inside the plugin dir.
ZipFile drops the `..` that pathlib keeps, so the zip writes such a name at another path than the
one every check measured, through any link the plugin's user put there."""

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from core.packages import archive, restore
from core.packages.integrity import ESCAPING_MEMBER, IntegrityError
from core.packages.own_file import own_file_sha256
from tests.core.packages import fake_changed_plugin, fake_partial_package

# Measured at the plugin dir's own daemon.bin, written at files/daemon.bin.
_CLIMBING_BACK = "files/../daemon.bin"
_CLIMBING_BYTES = b"bytes the climbing member carries"
_OUTSIDE_BYTES = b"a root-only file elsewhere on the printer"


def _entry(path: str, content: bytes) -> dict:
    return {"path": path, "sha256": hashlib.sha256(content).hexdigest(), "mode": "644"}


def _kept_binary_linked_out(plugin_dir: Path, tmp_path: Path) -> Path:
    outside_file = tmp_path / "root-only.bin"
    outside_file.write_bytes(_OUTSIDE_BYTES)
    (plugin_dir / "files/daemon.bin").unlink()
    (plugin_dir / "files/daemon.bin").symlink_to(outside_file)
    return outside_file


def _package_with_a_climbing_member(tmp_path: Path) -> Path:
    changed = fake_partial_package.CHANGED
    signed_files = [_entry(changed, b"v2.0\n"), _entry(_CLIMBING_BACK, _CLIMBING_BYTES)]
    package_manifest = {**fake_partial_package.manifest("2.0"), "files": signed_files}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr("manifest.json", json.dumps(package_manifest))
        package.writestr(changed, "v2.0\n")
        package.writestr(_CLIMBING_BACK, _CLIMBING_BYTES)
    package_path = tmp_path / "climbing.b3"
    package_path.write_bytes(buffer.getvalue())
    return package_path


def test_an_update_with_a_climbing_member_is_refused_before_it_writes_through_a_link(
    tmp_path: Path,
) -> None:
    plugin_dir = fake_partial_package.installed(tmp_path, b"the binary")
    outside_file = _kept_binary_linked_out(plugin_dir, tmp_path)

    with pytest.raises(IntegrityError) as refusal:
        archive.unpack_package(tmp_path, _package_with_a_climbing_member(tmp_path))

    assert (refusal.value.reason, refusal.value.paths) == (ESCAPING_MEMBER, [_CLIMBING_BACK])
    assert outside_file.read_bytes() == _OUTSIDE_BYTES


def test_a_restore_of_a_climbing_path_is_refused_before_it_writes_through_a_link(
    tmp_path: Path,
) -> None:
    """An install made before this refusal may already list such a path."""
    plugin_dir = fake_changed_plugin.installed(tmp_path)
    outside_file = _kept_binary_linked_out(plugin_dir, tmp_path)
    installed_manifest = {
        **fake_changed_plugin.INSTALLED_MANIFEST,
        "files": [_entry(_CLIMBING_BACK, _CLIMBING_BYTES)],
    }
    archive_path = fake_changed_plugin.zip_of(tmp_path, {_CLIMBING_BACK: _CLIMBING_BYTES})

    with pytest.raises(IntegrityError) as refusal, archive_path.open("rb") as restore_archive:
        restore.restore_files(plugin_dir, installed_manifest, restore_archive, "")

    assert (refusal.value.reason, refusal.value.paths) == (ESCAPING_MEMBER, [_CLIMBING_BACK])
    assert outside_file.read_bytes() == _OUTSIDE_BYTES


def test_a_climbing_path_is_never_the_plugins_own_file(tmp_path: Path) -> None:
    """A `..` steps back out of a folder opened without following a link."""
    plugin_dir = fake_changed_plugin.installed(tmp_path)

    assert own_file_sha256(plugin_dir, "files/../files/daemon.bin") is None
