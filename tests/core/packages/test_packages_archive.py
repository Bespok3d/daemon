import io
import json
import zipfile
from pathlib import Path

import pytest

from core.packages import archive, print_guard

MP = pytest.MonkeyPatch


def _make_b3(path: Path, manifest: dict, files: dict[str, str]) -> Path:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        for name, body in files.items():
            zf.writestr(name, body)
    path.write_bytes(buffer.getvalue())
    return path


def test_read_manifest_reads_without_extracting(tmp_path: Path) -> None:
    package = _make_b3(tmp_path / "p.b3", {"name": "alpha", "version": "1.0"}, {"files/x": "y"})
    assert archive.read_manifest(package) == {"name": "alpha", "version": "1.0"}


def test_is_doc_member_matches_doc_tree() -> None:
    assert archive._is_doc_member("doc")
    assert archive._is_doc_member("doc/README.md")
    assert not archive._is_doc_member("files/doc.cfg")


def test_unpack_package_extracts_and_skips_doc(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(print_guard, "_print_active", lambda: (False, "standby"))
    package = _make_b3(
        tmp_path / "p.b3",
        {"name": "alpha", "version": "1.0", "install": {"start": []}},
        {"files/run.sh": "echo hi", "doc/README.md": "# alpha", "doc": ""},
    )
    plugin_root = tmp_path / "plugins"
    manifest, plugin_dir, file_count = archive.unpack_package(plugin_root, package)
    assert manifest["name"] == "alpha"
    assert plugin_dir == plugin_root / "alpha"
    assert (plugin_dir / "files" / "run.sh").read_text() == "echo hi"
    assert not (plugin_dir / "doc").exists()
    assert file_count == 2  # manifest.json + files/run.sh, doc/* skipped


def test_unpack_package_rejects_archive_without_manifest(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(print_guard, "_print_active", lambda: (False, "standby"))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("files/x", "y")
    package = tmp_path / "no-manifest.b3"
    package.write_bytes(buffer.getvalue())
    with pytest.raises(ValueError, match="missing manifest.json"):
        archive.unpack_package(tmp_path / "plugins", package)


def test_fix_ownership_chmods_without_a_runtime_user(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "alpha"
    plugin_dir.mkdir()
    (plugin_dir / "run.sh").write_text("echo hi")
    phase = archive.fix_ownership(plugin_dir, "")
    assert phase["id"] == "ownership"
    assert all(item["ok"] for item in phase["items"])


def test_unpack_replaces_an_existing_file(tmp_path: Path, monkeypatch: MP) -> None:
    # A reinstall / version switch must replace files already on disk. Overwriting a running binary
    # in place raises ETXTBSY; _extract_members unlinks first, so extraction always succeeds.
    monkeypatch.setattr(print_guard, "_print_active", lambda: (False, "standby"))
    package = _make_b3(
        tmp_path / "p.b3",
        {"name": "alpha", "version": "1.0", "install": {"start": []}},
        {"files/bin/tool": "new"},
    )
    plugin_root = tmp_path / "plugins"
    dest = plugin_root / "alpha" / "files" / "bin" / "tool"
    dest.parent.mkdir(parents=True)
    dest.write_text("old")
    archive.unpack_package(plugin_root, package)
    assert dest.read_text() == "new"
