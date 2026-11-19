# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
import json
from pathlib import Path

import pytest

from core import packages
from core.packages.fingerprints import installed_fingerprints
from tests.package_fixtures import package_bytes

PACKED_FINGERPRINT = "ab" * 32
NO_INSTALL_STEPS: dict = {"dirs": [], "symlinks": [], "patches": []}


def write_installed_manifest(plugin_root: Path, plugin_id: str, manifest_text: str) -> None:
    plugin_dir = plugin_root / plugin_id
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text(manifest_text)


def test_a_plugin_packed_before_fingerprints_existed_is_left_out(tmp_path: Path) -> None:
    write_installed_manifest(tmp_path, "spoolman", json.dumps({"fingerprint": PACKED_FINGERPRINT}))
    write_installed_manifest(tmp_path, "camera", json.dumps({"version": "1.0.0"}))
    assert installed_fingerprints(tmp_path) == {"spoolman": PACKED_FINGERPRINT}


def test_a_fingerprint_that_is_not_text_is_left_out(tmp_path: Path) -> None:
    write_installed_manifest(tmp_path, "camera", json.dumps({"fingerprint": 42}))
    assert installed_fingerprints(tmp_path) == {}


def test_a_torn_manifest_is_left_out(tmp_path: Path) -> None:
    write_installed_manifest(tmp_path, "camera", '{"fingerprint": "ab')
    assert installed_fingerprints(tmp_path) == {}


def test_a_printer_with_no_plugin_root_reports_none(tmp_path: Path) -> None:
    assert installed_fingerprints(tmp_path / "absent") == {}


def test_the_fingerprint_is_read_back_from_the_installed_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    monkeypatch.setattr(packages, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(packages, "PLUGIN_ROOT", plugin_root)
    manifest = {
        "name": "demo", "version": "1.0.0", "install": NO_INSTALL_STEPS,
        "fingerprint": PACKED_FINGERPRINT,
    }
    package_path = tmp_path / "demo.b3"
    package_path.write_bytes(package_bytes(manifest, {"files/x.cfg": "DATA"}))

    packages.install(package_path, {})

    assert installed_fingerprints(plugin_root) == {"demo": PACKED_FINGERPRINT}
