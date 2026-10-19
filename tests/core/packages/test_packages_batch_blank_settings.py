# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A blank setting in a batched install is judged by the manifest, never by the charset check.

The bug: the charset check refused every blank value, so a plugin whose optional setting defaults to
"" (Spoolman's location) could not be installed at all. A blank required value stays the
missing-setting refusal, and an unsafe non-blank value stays the unusable-characters refusal.
"""
from pathlib import Path

import pytest

from core import packages
from tests.package_fixtures import package_bytes

MP = pytest.MonkeyPatch

LOCATION_TEMPLATE = "server: $SPOOLMAN_SERVER\nlocation: $SPOOLMAN_LOCATION\n"
LOCATION_MANIFEST = {
    "name": "spoolman",
    "version": "0.1.0",
    "install": {
        "dirs": [], "symlinks": [], "patches": [], "start": [],
        "templates": [{"from": "files/spoolman.tmpl", "to": "files/spoolman.cfg"}],
    },
    "requires": {"variables": [
        {"name": "SPOOLMAN_SERVER", "required": True},
        {"name": "SPOOLMAN_LOCATION", "required": False, "default": ""},
    ]},
}
REACHABLE_SERVER = "http://spoolman:8000"


@pytest.fixture
def installed_root(plugin_root: Path, monkeypatch: MP) -> Path:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", plugin_root)
    return plugin_root


def _install_with_settings(tmp_path: Path, settings: dict[str, str]) -> dict:
    package_path = tmp_path / "spoolman.b3"
    package_path.write_bytes(package_bytes(
        LOCATION_MANIFEST, {"files/spoolman.tmpl": LOCATION_TEMPLATE},
    ))
    return packages.install_batch({}, [package_path], {"spoolman": settings})[0]


def test_a_blank_optional_setting_installs(tmp_path: Path, installed_root: Path) -> None:
    result = _install_with_settings(
        tmp_path, {"SPOOLMAN_SERVER": REACHABLE_SERVER, "SPOOLMAN_LOCATION": ""},
    )

    assert result["ok"] is True
    rendered = (installed_root / "spoolman" / "files" / "spoolman.cfg").read_text()
    assert rendered == f"server: {REACHABLE_SERVER}\nlocation: \n"


def test_a_blank_required_setting_is_refused_as_missing(
    tmp_path: Path, installed_root: Path,
) -> None:
    result = _install_with_settings(tmp_path, {"SPOOLMAN_SERVER": "", "SPOOLMAN_LOCATION": ""})

    assert result["ok"] is False
    assert "allows only" not in result["reason"]
    assert "SPOOLMAN_SERVER" in result["reason"]
    assert not (installed_root / "spoolman").exists()


def test_an_unsafe_setting_is_still_refused_for_its_characters(
    tmp_path: Path, installed_root: Path,
) -> None:
    result = _install_with_settings(
        tmp_path, {"SPOOLMAN_SERVER": REACHABLE_SERVER, "SPOOLMAN_LOCATION": "shelf; reboot"},
    )

    assert result["ok"] is False
    assert "allows only" in result["reason"]
    assert not (installed_root / "spoolman").exists()
