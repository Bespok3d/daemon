# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Refusals unpack_package must make that the happy-path suite never exercises: a package is
untrusted input from the internet, so a malformed or path-escaping archive must be refused before
a single byte lands on the printer.
"""

import io
import json
import stat
import zipfile
from pathlib import Path

import pytest

from core.packages import archive
from core.packages.integrity import ESCAPING_MEMBER, IntegrityError


def _raw_b3(path: Path, manifest: dict, members_by_name: dict[str, str]) -> Path:
    """A package built WITHOUT deriving files[]: the shape a crafted archive has, where the member
    list and the signed manifest disagree."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr("manifest.json", json.dumps(manifest))
        for name, body in members_by_name.items():
            package.writestr(name, body)
    path.write_bytes(buffer.getvalue())
    return path


def test_unpack_refuses_a_declared_path_escaping_with_no_escaping_member(tmp_path: Path) -> None:
    """apply_modes chmods every files[] path as root, so a manifest that declares a `..` path must
    be refused even when the archive ships no member at that path at all."""
    package = _raw_b3(
        tmp_path / "p.b3",
        {
            "name": "alpha", "version": "1.0", "install": {"start": []},
            "files": [
                {"path": "files/run.sh", "sha256": "irrelevant", "mode": "644"},
                {"path": "../evil.cfg", "sha256": "irrelevant", "mode": "644"},
            ],
        },
        {"files/run.sh": "echo hi"},
    )
    plugin_root = tmp_path / "plugins"

    with pytest.raises(IntegrityError) as refusal:
        archive.unpack_package(plugin_root, package)

    assert refusal.value.reason == ESCAPING_MEMBER
    assert refusal.value.paths == ["../evil.cfg"]
    assert not (plugin_root / "alpha").exists()


@pytest.mark.parametrize(
    "body",
    [b"garbage bytes, not a zip central directory", b""],
    ids=["truncated_or_garbage", "empty_file"],
)
def test_unpack_refuses_a_file_that_is_not_a_valid_archive(tmp_path: Path, body: bytes) -> None:
    """A download cut short, or a placeholder that never became a real package, must be refused
    before the plugin root is ever created, not partially unpacked."""
    package = tmp_path / "bad.b3"
    package.write_bytes(body)
    plugin_root = tmp_path / "plugins"

    with pytest.raises(zipfile.BadZipFile):
        archive.unpack_package(plugin_root, package)

    assert not plugin_root.exists()


def test_symlink_member_lands_as_ordinary_file_content_never_a_live_link(tmp_path: Path) -> None:
    """A member flagged as a Unix symlink whose target escapes the plugin dir must not become a
    real symlink on the printer: extraction has to write its target string as inert file content."""
    manifest = {
        "name": "alpha", "version": "1.0", "install": {"start": []},
        "files": [{"path": "files/link", "sha256": "irrelevant", "mode": "644"}],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr("manifest.json", json.dumps(manifest))
        link_info = zipfile.ZipInfo("files/link")
        link_info.create_system = 3
        link_info.external_attr = (stat.S_IFLNK | 0o777) << 16
        package.writestr(link_info, "../../../etc/passwd")
    package_path = tmp_path / "p.b3"
    package_path.write_bytes(buffer.getvalue())
    plugin_root = tmp_path / "plugins"

    _manifest, plugin_dir, _file_count = archive.unpack_package(plugin_root, package_path)

    link_member = plugin_dir / "files" / "link"
    assert not link_member.is_symlink()
    assert link_member.read_text() == "../../../etc/passwd"


def _package_declaring_unbaked_deps(path: Path) -> Path:
    """A build fault: the plugin declares Python deps and the .b3 carries nothing baked for them."""
    return _raw_b3(
        path,
        {"name": "alpha", "version": "2.0", "install": {"start": []},
         "files": [{"path": "requirements.txt", "sha256": "irrelevant", "mode": "644"}]},
        {"requirements.txt": "humanize>=4.9.0\n"},
    )


def test_a_refused_update_keeps_the_installed_plugin_stock_originals(tmp_path: Path) -> None:
    """The plugin directory is also where the version on the printer keeps the stock originals of
    the files it patched and the settings the user typed. A refusal must not delete it: the printer
    would be left patched with the only copy of the original gone."""
    plugin_root = tmp_path / "plugins"
    installed = plugin_root / "alpha"
    (installed / "patches_orig").mkdir(parents=True)
    (installed / "patches_orig" / "printer.cfg").write_text("stock printer.cfg")
    (installed / "user_vars.json").write_text('{"port": "7125"}')

    with pytest.raises(ValueError, match="requirements.txt"):
        archive.unpack_package(plugin_root, _package_declaring_unbaked_deps(tmp_path / "p.b3"))

    assert (installed / "patches_orig" / "printer.cfg").read_text() == "stock printer.cfg"
    assert (installed / "user_vars.json").read_text() == '{"port": "7125"}'


def test_a_refused_first_install_leaves_nothing_behind(tmp_path: Path) -> None:
    """Nothing was on the printer to protect, so the extraction is taken back off it: kept, the tree
    would make the daemon report a plugin it never installed."""
    plugin_root = tmp_path / "plugins"
    with pytest.raises(ValueError, match="requirements.txt"):
        archive.unpack_package(plugin_root, _package_declaring_unbaked_deps(tmp_path / "p.b3"))
    assert not (plugin_root / "alpha").exists()
