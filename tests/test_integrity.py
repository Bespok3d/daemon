# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""verify_files must match a plugin's on-disk files against the sha256 the packer recorded in the
manifest, and an install must refuse a mismatch before a single phase runs
(tmp_path-based style, no custom fixture, per tests/test_generic_daemon_guard.py)."""

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from core.packages import installer
from core.packages.file_drift import changed_files, refuse_changed_package
from core.packages.integrity import CHECKSUM_MISMATCH, IntegrityError, verify_files


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_plugin(plugin_dir: Path) -> list[dict]:
    plugin_dir.mkdir()
    contents = {"a.txt": b"hello", "sub/b.txt": b"world"}
    manifest_files = []
    for relative, data in contents.items():
        target = plugin_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest_files.append({"path": relative, "sha256": _digest(data), "mode": "644"})
    return manifest_files


def test_a_clean_tree_returns_no_mismatches(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plug"
    manifest_files = _write_plugin(plugin_dir)

    assert verify_files(plugin_dir, manifest_files) == []


def test_a_corrupted_file_is_flagged(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plug"
    manifest_files = _write_plugin(plugin_dir)
    (plugin_dir / "a.txt").write_bytes(b"tampered")

    assert verify_files(plugin_dir, manifest_files) == ["a.txt"]


def test_a_missing_file_is_flagged(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plug"
    manifest_files = _write_plugin(plugin_dir)
    (plugin_dir / "sub" / "b.txt").unlink()

    assert verify_files(plugin_dir, manifest_files) == ["sub/b.txt"]


def test_an_install_refuses_a_corrupted_file(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plug"
    manifest_files = _write_plugin(plugin_dir)
    (plugin_dir / "a.txt").write_bytes(b"tampered")
    manifest = {"name": "plug", "install": {}, "files": manifest_files}

    with pytest.raises(IntegrityError) as excinfo:
        refuse_changed_package(plugin_dir, manifest)

    assert excinfo.value.reason == CHECKSUM_MISMATCH
    assert excinfo.value.paths == ["a.txt"]


def test_the_phase_runner_no_longer_judges_the_files_it_applies(tmp_path: Path) -> None:
    """Recovery re-applies the tree already on the printer, where another plugin may have edited a
    file, so the verdict belongs to install and update and never to the shared phase runner."""
    plugin_dir = tmp_path / "plug"
    manifest_files = _write_plugin(plugin_dir)
    (plugin_dir / "a.txt").write_bytes(b"edited by another plugin")
    manifest = {"name": "plug", "install": {}, "files": manifest_files}

    phases, _ = installer.apply_install_deferred(tmp_path, plugin_dir, manifest, {})

    assert phases


def test_a_manifest_that_lists_the_doc_tree_is_not_called_changed(tmp_path: Path) -> None:
    """b3-builder lists doc/ in files[] and unpack_package deletes it, so hashing every listed entry
    would call every doc-carrying package tampered and let no such plugin install at all."""
    plugin_dir = tmp_path / "plug"
    manifest_files = _write_plugin(plugin_dir)
    unwritten_doc = {"path": "doc/guide.md", "sha256": _digest(b"never unpacked"), "mode": "644"}
    manifest = {"name": "plug", "install": {}, "files": [*manifest_files, unwritten_doc]}

    assert changed_files(plugin_dir, manifest) == []


def _pack_tampered_package(package_path: Path) -> None:
    """A .b3 whose manifest advertises the packer's sha256 while the payload underneath it differs:
    what a package altered in transit or at rest looks like."""
    manifest = {
        "name": "plug",
        "install": {},
        "files": [{"path": "files/a.txt", "sha256": _digest(b"as packed"), "mode": "644"}],
    }
    with zipfile.ZipFile(package_path, "w") as package:
        package.writestr("manifest.json", json.dumps(manifest))
        package.writestr("files/a.txt", b"tampered after packing")


def test_a_refused_install_leaves_no_unpacked_tree_behind(tmp_path: Path) -> None:
    """A refusal that kept the unpacked tree would make /capabilities report a plugin the daemon
    never applied, so the refused install must take its own extraction with it."""
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    package_path = tmp_path / "plug.b3"
    _pack_tampered_package(package_path)

    with pytest.raises(IntegrityError):
        installer.run_install(plugin_root, package_path, {})

    assert not (plugin_root / "plug").exists()
