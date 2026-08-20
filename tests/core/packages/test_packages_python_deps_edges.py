# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Edge cases the happy-path suite (test_packages_python_deps.py) does not cover: a partial CI bake
that reject_unbaked_deps should catch before install starts but does not, and the must-refuse /
must-survive shapes of the actual provisioning entry point (provision_deps_phases). No pip runs and
no venv is built: the only subprocess call this module makes (_already_importable's python3 probe)
is stubbed, and the system-site-packages linking goes through the repo's fake jinni (autouse in
tests/core/conftest.py), which only ever performs real symlinks, never a subprocess.
"""
from pathlib import Path

import pytest

from core import python_env
from core.packages import baked_deps, python_deps

MP = pytest.MonkeyPatch


class _FakeImportProbe:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode


def _stub_nothing_already_importable(monkeypatch: MP) -> None:
    """Force _already_importable's own subprocess probe to report "not on the system Python",
    deterministically, instead of shelling out to a real python3 -c import check."""
    monkeypatch.setattr(python_deps.subprocess, "run", lambda *_a, **_kw: _FakeImportProbe(1))


def _bake_widgetlib(plugin_dir: Path, version: str) -> Path:
    """A baked site-packages package dir plus its dist-info, named widgetlib at the given version:
    the shape baked_top_level_names and _baked_version both read."""
    baked = python_env.baked_site_packages_dir(plugin_dir)
    baked.mkdir(parents=True)
    (baked / "widgetlib").mkdir()
    (baked / f"widgetlib-{version}.dist-info").mkdir()
    return baked / "widgetlib"


def test_reject_unbaked_deps_misses_a_wheels_dir_with_no_wheel_in_it(tmp_path: Path) -> None:
    """A requirements.txt whose baked wheels dir holds only CI leftovers, no .whl file, must be
    refused as unbaked: nothing offline for provision_venv_phase to install."""
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    (plugin_dir / "requirements.txt").write_text("humanize>=4.9.0")
    wheels_dir = python_env.plugin_wheels_dir(plugin_dir)
    wheels_dir.mkdir(parents=True)
    (wheels_dir / "build_notes.txt").write_text("ci left this, not a wheel")
    with pytest.raises(ValueError, match="files/wheels"):
        baked_deps.reject_unbaked_deps(plugin_dir)


def test_reject_unbaked_deps_misses_dist_info_with_no_importable_package(tmp_path: Path) -> None:
    """A klipper_requirements.txt whose baked site-packages dir holds only the package's metadata
    (a partial bake) must be refused: baked_top_level_names filters dist-info out, so nothing would
    ever be linked for Klipper to import."""
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    (plugin_dir / "klipper_requirements.txt").write_text("widgetlib==1.0.0")
    site_packages_dir = python_env.baked_site_packages_dir(plugin_dir)
    site_packages_dir.mkdir(parents=True)
    (site_packages_dir / "widgetlib-1.0.0.dist-info").mkdir()
    with pytest.raises(ValueError, match="files/site-packages"):
        baked_deps.reject_unbaked_deps(plugin_dir)


def test_provision_deps_phases_is_empty_for_a_plugin_with_no_dependency_file(tmp_path: Path) -> None:  # noqa: E501
    """A plugin that ships neither requirements.txt nor klipper_requirements.txt installs with no
    phantom Python phase in its log."""
    plugin_root = tmp_path / "plugins"
    plugin_dir = plugin_root / "bareplugin"
    plugin_dir.mkdir(parents=True)
    vars = {"PYTHON_SITE_PACKAGES": str(tmp_path / "site-packages")}
    assert python_deps.provision_deps_phases(plugin_root, plugin_dir, vars) == []


def test_link_refuses_a_real_file_already_at_the_destination_name(
    tmp_path: Path, monkeypatch: MP,
) -> None:
    """A stock file already occupying the target site-packages name (not our own earlier symlink)
    must never be overwritten by a plugin's baked package of the same name."""
    _stub_nothing_already_importable(monkeypatch)
    plugin_root = tmp_path / "plugins"
    plugin_dir = plugin_root / "onlyplugin"
    _bake_widgetlib(plugin_dir, "1.0.0")
    (plugin_dir / "klipper_requirements.txt").write_text("widgetlib==1.0.0")
    site_packages_dir = tmp_path / "site-packages"
    site_packages_dir.mkdir()
    (site_packages_dir / "widgetlib").write_text("stock klipper extra, not ours")

    vars = {"PYTHON_SITE_PACKAGES": str(site_packages_dir)}
    phases = python_deps.provision_deps_phases(plugin_root, plugin_dir, vars)

    assert len(phases) == 1
    assert phases[0]["ok"] is False
    assert "already occupies" in phases[0]["items"][0]["label"]
    assert (site_packages_dir / "widgetlib").read_text() == "stock klipper extra, not ours"


def test_link_refuses_a_different_version_already_linked_by_another_plugin(
    tmp_path: Path, monkeypatch: MP,
) -> None:
    """Two plugins baking different versions of one package must not both link it into one system
    interpreter: the second link is refused, the first plugin's link stays intact."""
    _stub_nothing_already_importable(monkeypatch)
    plugin_root = tmp_path / "plugins"
    first_package = _bake_widgetlib(plugin_root / "pluginone", "1.0.0")
    site_packages_dir = tmp_path / "site-packages"
    site_packages_dir.mkdir()
    (site_packages_dir / "widgetlib").symlink_to(first_package)

    plugin_dir = plugin_root / "plugintwo"
    _bake_widgetlib(plugin_dir, "2.0.0")
    (plugin_dir / "klipper_requirements.txt").write_text("widgetlib==2.0.0")

    vars = {"PYTHON_SITE_PACKAGES": str(site_packages_dir)}
    phases = python_deps.provision_deps_phases(plugin_root, plugin_dir, vars)

    assert len(phases) == 1
    assert phases[0]["ok"] is False
    assert "different version" in phases[0]["items"][0]["label"]
    assert (site_packages_dir / "widgetlib").resolve() == first_package.resolve()
