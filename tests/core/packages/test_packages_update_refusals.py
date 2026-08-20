# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A batched update declines what a batched install declines, before a byte lands on the printer.

Updating several plugins at once is the same thing as updating them one at a time, so a package
whose required service nothing supplies, or that excludes a plugin already on the printer, is
refused with nothing unpacked. Without this the update path was the one way onto the printer that
skipped the dependency and conflict checks the install path has always run.
"""
from pathlib import Path

import pytest

from core import packages
from core.packages import updater
from tests.package_fixtures import package_bytes

MP = pytest.MonkeyPatch


def _package(tmp_path: Path, plugin_id: str, manifest_extras: dict) -> Path:
    manifest = {
        "name": plugin_id,
        "version": "0.1.0",
        "install": {
            "dirs": [], "symlinks": [], "patches": [], "start": [], "templates": [],
        },
        **manifest_extras,
    }
    members = {"files/settings.cfg": f"owner: {plugin_id}\n"}
    package_path = tmp_path / f"{plugin_id}.b3"
    package_path.write_bytes(package_bytes(manifest, members))
    return package_path


def _install_a_provider(plugin_root: Path, plugin_id: str, service: str) -> None:
    """A plugin already on the printer, written the way an earlier install left it."""
    plugin_dir = plugin_root / plugin_id
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text(
        f'{{"name": "{plugin_id}", "version": "0.1.0", "provides": ["{service}"]}}',
    )


def test_an_update_needing_an_absent_service_is_refused_with_nothing_written(
    tmp_path: Path, monkeypatch: MP,
) -> None:
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    monkeypatch.setattr(packages, "PLUGIN_ROOT", plugin_root)
    needs_absent_service = _package(
        tmp_path, "spoolman", {"require": [{"service": "filament-db"}]},
    )

    results = updater.run_update_batch(plugin_root, {}, [needs_absent_service], {})

    refused = {result["plugin_id"]: result for result in results}["spoolman"]
    assert refused["ok"] is False
    assert "filament-db" in refused["reason"]
    assert not (plugin_root / "spoolman").exists()


def test_an_update_excluding_an_installed_plugin_is_refused_with_nothing_written(
    tmp_path: Path, monkeypatch: MP,
) -> None:
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    monkeypatch.setattr(packages, "PLUGIN_ROOT", plugin_root)
    _install_a_provider(plugin_root, "rfid-ntag", "rfid")
    excludes_it = _package(tmp_path, "spoolman", {"conflicts": ["rfid-ntag"]})

    results = updater.run_update_batch(plugin_root, {}, [excludes_it], {})

    refused = {result["plugin_id"]: result for result in results}["spoolman"]
    assert refused["ok"] is False
    assert "rfid-ntag" in refused["reason"]
    assert not (plugin_root / "spoolman").exists()


def test_a_sibling_in_the_same_update_supplies_the_service(
    tmp_path: Path, monkeypatch: MP,
) -> None:
    """The check looks at the whole batch, so updating a provider and its dependent together is not
    a refusal: the provider is right there in the same sweep."""
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    monkeypatch.setattr(packages, "PLUGIN_ROOT", plugin_root)
    provider = _package(tmp_path, "filament-db-plugin", {"provides": ["filament-db"]})
    dependent = _package(tmp_path, "spoolman", {"require": [{"service": "filament-db"}]})

    results = updater.run_update_batch(plugin_root, {}, [provider, dependent], {})

    by_id = {result["plugin_id"]: result for result in results}
    assert by_id["spoolman"]["ok"] is True
    assert by_id["filament-db-plugin"]["ok"] is True
