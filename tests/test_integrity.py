"""verify_files must match a plugin's on-disk files against the sha256 the packer recorded in the
manifest, and apply_install_deferred must refuse a mismatch before its phase list is even built
(tmp_path-based style, no custom fixture, per tests/test_generic_daemon_guard.py)."""

import hashlib
from pathlib import Path

import pytest

from core.packages import installer
from core.packages.integrity import IntegrityError, verify_files


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


def test_apply_install_deferred_refuses_a_corrupted_file_before_any_phase_runs(
    tmp_path: Path,
) -> None:
    plugin_dir = tmp_path / "plug"
    manifest_files = _write_plugin(plugin_dir)
    (plugin_dir / "a.txt").write_bytes(b"tampered")
    manifest = {"name": "plug", "install": {}, "files": manifest_files}
    seen: list[dict] = []

    with pytest.raises(IntegrityError) as excinfo:
        installer.apply_install_deferred(tmp_path, plugin_dir, manifest, {}, seen.append)

    assert excinfo.value.mismatched == ["a.txt"]
    assert seen == []
