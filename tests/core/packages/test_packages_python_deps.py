# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
from pathlib import Path

import pytest

from core.packages import baked_deps

MP = pytest.MonkeyPatch


def test_reject_conflicting_dep_files_raises_when_both_present(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("a")
    (tmp_path / "klipper_requirements.txt").write_text("b")
    with pytest.raises(ValueError, match="not both"):
        baked_deps.reject_conflicting_dep_files(tmp_path)


def test_reject_conflicting_dep_files_allows_one_or_neither(tmp_path: Path) -> None:
    baked_deps.reject_conflicting_dep_files(tmp_path)
    (tmp_path / "requirements.txt").write_text("a")
    baked_deps.reject_conflicting_dep_files(tmp_path)


def test_reject_unbaked_deps_raises_when_wheels_missing(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("humanize>=4.9.0")
    with pytest.raises(ValueError, match="files/wheels"):
        baked_deps.reject_unbaked_deps(tmp_path)


def test_reject_unbaked_deps_raises_when_site_packages_missing(tmp_path: Path) -> None:
    (tmp_path / "klipper_requirements.txt").write_text("humanize>=4.9.0")
    with pytest.raises(ValueError, match="files/site-packages"):
        baked_deps.reject_unbaked_deps(tmp_path)


def test_baked_top_level_names_filters_metadata_and_sorts(tmp_path: Path) -> None:
    baked = tmp_path / "files" / "site-packages"
    baked.mkdir(parents=True)
    (baked / "humanize").mkdir()
    (baked / "click.py").write_text("")
    (baked / "humanize-4.15.0.dist-info").mkdir()
    (baked / "bin").mkdir()
    (baked / "__pycache__").mkdir()
    assert baked_deps.baked_top_level_names(tmp_path) == ["click.py", "humanize"]


def test_baked_top_level_names_empty_without_a_baked_dir(tmp_path: Path) -> None:
    assert baked_deps.baked_top_level_names(tmp_path) == []
