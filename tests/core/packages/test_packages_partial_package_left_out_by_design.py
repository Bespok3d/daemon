# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Listed files a package may leave out even on a first install, because the printer never takes
them from the zip: a template's render target, which install writes itself, and the docs, which are
never deployed."""

import json
import zipfile
from pathlib import Path

from core.packages import archive
from tests.core.packages.fake_partial_package import CHANGED, KEPT, KEPT_BYTES, entry, manifest


def test_a_left_out_render_target_does_not_refuse_the_package(tmp_path: Path) -> None:
    """Install renders that file from the template after unpacking, so the zip need not carry it."""
    template, rendered = "files/settings.cfg.tmpl", "files/rendered.cfg"
    rendering_manifest = {**manifest("1.0"), "files": [entry(template, b"port = {port}\n"),
                                                       entry(rendered, b"port = 7912\n")]}
    rendering_manifest["install"] = {**rendering_manifest["install"],
                                     "templates": [{"from": template, "to": rendered}]}
    package_path = tmp_path / "rendered.b3"
    with zipfile.ZipFile(package_path, "w") as package:
        package.writestr("manifest.json", json.dumps(rendering_manifest))
        package.writestr(template, "port = {port}\n")

    _manifest_read, plugin_dir, _count, _replacing = archive.unpack_package(
        tmp_path / "plugins", package_path)

    assert (plugin_dir / template).is_file()
    assert not (plugin_dir / rendered).exists()


def test_left_out_docs_do_not_refuse_a_first_install(tmp_path: Path) -> None:
    """Docs ship inside the package but are never deployed, so nothing on disk could vouch."""
    documented_manifest = manifest("1.0")
    documented_manifest["files"] = [*documented_manifest["files"], entry("doc/README.md", b"docs")]
    package_path = tmp_path / "documented.b3"
    with zipfile.ZipFile(package_path, "w") as package:
        package.writestr("manifest.json", json.dumps(documented_manifest))
        package.writestr(KEPT, KEPT_BYTES)
        package.writestr(CHANGED, "v1.0\n")

    _manifest_read, plugin_dir, _count, _replacing = archive.unpack_package(
        tmp_path / "plugins", package_path)

    assert (plugin_dir / KEPT).read_bytes() == KEPT_BYTES
