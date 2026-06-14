from pathlib import Path

import pytest

from core import packages
from core.packages import python_deps

MP = pytest.MonkeyPatch


def test_orchestrator_reexports_the_public_dep_helpers() -> None:
    assert packages.provision_deps_phases is python_deps.provision_deps_phases
    assert packages.remove_plugin_site_links is python_deps.remove_plugin_site_links
    assert packages.remove_plugin_venv is python_deps.remove_plugin_venv


def test_reject_conflicting_dep_files_raises_when_both_present(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("a")
    (tmp_path / "klipper_requirements.txt").write_text("b")
    with pytest.raises(ValueError, match="not both"):
        python_deps.reject_conflicting_dep_files(tmp_path)


def test_reject_conflicting_dep_files_allows_one_or_neither(tmp_path: Path) -> None:
    python_deps.reject_conflicting_dep_files(tmp_path)
    (tmp_path / "requirements.txt").write_text("a")
    python_deps.reject_conflicting_dep_files(tmp_path)


def test_reject_unbaked_deps_raises_when_wheels_missing(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("humanize>=4.9.0")
    with pytest.raises(ValueError, match="files/wheels"):
        python_deps.reject_unbaked_deps(tmp_path)


def test_reject_unbaked_deps_raises_when_site_packages_missing(tmp_path: Path) -> None:
    (tmp_path / "klipper_requirements.txt").write_text("humanize>=4.9.0")
    with pytest.raises(ValueError, match="files/site-packages"):
        python_deps.reject_unbaked_deps(tmp_path)


def test_baked_top_level_names_filters_metadata_and_sorts(tmp_path: Path) -> None:
    baked = tmp_path / "files" / "site-packages"
    baked.mkdir(parents=True)
    (baked / "humanize").mkdir()
    (baked / "click.py").write_text("")
    (baked / "humanize-4.15.0.dist-info").mkdir()
    (baked / "bin").mkdir()
    (baked / "__pycache__").mkdir()
    assert python_deps.baked_top_level_names(tmp_path) == ["click.py", "humanize"]


def test_baked_top_level_names_empty_without_a_baked_dir(tmp_path: Path) -> None:
    assert python_deps.baked_top_level_names(tmp_path) == []
