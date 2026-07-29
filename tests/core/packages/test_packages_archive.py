# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
import io
import json
import zipfile
from pathlib import Path

import pytest

from core.packages import archive, members
from core.packages.integrity import (
    ESCAPING_MEMBER,
    ESCAPING_PLUGIN_ID,
    UNDECLARED_MEMBER,
    IntegrityError,
)
from tests.package_fixtures import package_bytes

MP = pytest.MonkeyPatch


def _make_b3(path: Path, manifest: dict, files: dict[str, str]) -> Path:
    path.write_bytes(package_bytes(manifest, files))
    return path


def test_read_manifest_reads_without_extracting(tmp_path: Path) -> None:
    package = _make_b3(tmp_path / "p.b3", {"name": "alpha", "version": "1.0"}, {"files/x": "y"})
    manifest = archive.read_manifest(package)
    assert manifest["name"] == "alpha"
    assert manifest["version"] == "1.0"


def test_is_doc_member_matches_doc_tree() -> None:
    assert members.is_doc_member("doc")
    assert members.is_doc_member("doc/README.md")
    assert not members.is_doc_member("files/doc.cfg")


def test_unpack_package_extracts_and_skips_doc(tmp_path: Path, monkeypatch: MP) -> None:
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


def _b3_with_raw_members(path: Path, manifest: dict, members_by_name: dict[str, str]) -> Path:
    """A package built WITHOUT deriving files[]: the shape a crafted archive has, where the member
    list and the signed manifest disagree."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr("manifest.json", json.dumps(manifest))
        for name, body in members_by_name.items():
            package.writestr(name, body)
    path.write_bytes(buffer.getvalue())
    return path


def test_unpack_refuses_a_member_the_manifest_never_listed(tmp_path: Path) -> None:
    package = _b3_with_raw_members(
        tmp_path / "p.b3",
        {
            "name": "alpha", "version": "1.0", "install": {"start": []},
            "files": [{"path": "files/run.sh", "sha256": "irrelevant", "mode": "644"}],
        },
        {"files/run.sh": "echo hi", "files/stowaway.sh": "echo pwned"},
    )
    plugin_root = tmp_path / "plugins"

    with pytest.raises(IntegrityError) as refusal:
        archive.unpack_package(plugin_root, package)

    assert refusal.value.reason == UNDECLARED_MEMBER
    assert refusal.value.paths == ["files/stowaway.sh"]
    # Refused before the plugin dir exists, so a refused reinstall cannot damage what it replaces.
    assert not (plugin_root / "alpha").exists()


def test_unpack_accepts_the_members_a_manifest_cannot_list(tmp_path: Path) -> None:
    package = _make_b3(
        tmp_path / "p.b3",
        {"name": "alpha", "version": "1.0", "install": {"start": []}},
        {"files/run.sh": "echo hi", "doc/README.md": "# alpha", "manifest.json.sig": "-----SIG"},
    )
    plugin_root = tmp_path / "plugins"

    _manifest, plugin_dir, _file_count = archive.unpack_package(plugin_root, package)

    assert (plugin_dir / "manifest.json.sig").read_text() == "-----SIG"
    assert not (plugin_dir / "doc").exists()


def test_unpack_refuses_an_absolute_member_before_unlinking_it(tmp_path: Path) -> None:
    outsider = tmp_path / "outside" / "S99bespok3d"
    outsider.parent.mkdir()
    outsider.write_text("init script")
    package = _b3_with_raw_members(
        tmp_path / "p.b3",
        {
            "name": "alpha", "version": "1.0", "install": {"start": []},
            "files": [{"path": str(outsider), "sha256": "irrelevant", "mode": "644"}],
        },
        {str(outsider): "clobbered"},
    )
    plugin_root = tmp_path / "plugins"

    with pytest.raises(IntegrityError) as refusal:
        archive.unpack_package(plugin_root, package)

    assert refusal.value.reason == ESCAPING_MEMBER
    assert outsider.read_text() == "init script"


def test_unpack_refuses_a_plugin_name_that_is_not_a_plain_directory_name(tmp_path: Path) -> None:
    """Containment is measured against the plugin dir, and the package names it: a name carrying a
    path relocates the whole extraction, and every member then measures as "inside" the new root."""
    plugin_root = tmp_path / "userdata" / "plugins"
    init_d = tmp_path / "etc" / "init.d"
    init_d.mkdir(parents=True)
    outsider = init_d / "S99bespok3d"
    outsider.write_text("init script")
    package = _b3_with_raw_members(
        tmp_path / "p.b3",
        {
            "name": "../../etc/init.d", "version": "1.0", "install": {"start": []},
            "files": [{"path": "S99bespok3d", "sha256": "irrelevant", "mode": "644"}],
        },
        {"S99bespok3d": "clobbered"},
    )

    with pytest.raises(IntegrityError) as refusal:
        archive.unpack_package(plugin_root, package)

    assert refusal.value.reason == ESCAPING_PLUGIN_ID
    assert outsider.read_text() == "init script"


def test_unpack_refuses_a_package_whose_files_declaration_is_malformed(tmp_path: Path) -> None:
    """A files[] the daemon cannot read declares nothing, so its members are refused as undeclared:
    a refusal the app can render, not a crash the user sees as an unexplained daemon fault."""
    package = _b3_with_raw_members(
        tmp_path / "p.b3",
        {"name": "alpha", "version": "1.0", "install": {"start": []}, "files": None},
        {"files/run.sh": "echo hi"},
    )

    with pytest.raises(IntegrityError) as refusal:
        archive.unpack_package(tmp_path / "plugins", package)

    assert refusal.value.reason == UNDECLARED_MEMBER


def test_unpack_refuses_a_traversing_member_before_unlinking_it(tmp_path: Path) -> None:
    plugin_root = tmp_path / "plugins"
    outsider = plugin_root / "victim.cfg"
    plugin_root.mkdir()
    outsider.write_text("someone else's file")
    traversal = "../victim.cfg"
    package = _b3_with_raw_members(
        tmp_path / "p.b3",
        {
            "name": "alpha", "version": "1.0", "install": {"start": []},
            "files": [{"path": traversal, "sha256": "irrelevant", "mode": "644"}],
        },
        {traversal: "clobbered"},
    )

    with pytest.raises(IntegrityError) as refusal:
        archive.unpack_package(plugin_root, package)

    assert refusal.value.reason == ESCAPING_MEMBER
    assert outsider.read_text() == "someone else's file"
