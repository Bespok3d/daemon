# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A baked wheel whose installed RECORD is gone loses its dist-info before the offline install.

pip uninstalls a distribution by that RECORD before it installs over it, the same version or an
upgrade alike, and fails without one; with the dist-info gone it installs the wheel as new."""
from pathlib import Path

import pytest

from core.packages import plugin_venv
from tests.core.packages.fake_plugin_venv import (
    HUMANIZE_DIST_INFO,
    SITE_PACKAGES,
    healthy_venv,
    install_distribution,
    provision,
)


def _refuse_removal(dist_info: Path) -> None:
    raise PermissionError(f"Operation not permitted: {dist_info.name}")


def test_a_dist_info_without_its_record_is_gone_before_the_install_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist_info = healthy_venv(tmp_path) / SITE_PACKAGES / HUMANIZE_DIST_INFO
    (dist_info / "RECORD").unlink()

    python_phase, pip_runs = provision(tmp_path, monkeypatch, exit_codes=[0, 0], watched=dist_info)

    assert pip_runs.watched_was_there[0] is False
    assert "--force-reinstall" not in pip_runs.commands[0]
    assert python_phase["ok"] is True


def test_an_older_version_without_its_record_is_gone_before_the_upgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    site_packages = healthy_venv(tmp_path) / SITE_PACKAGES
    older_dist_info = site_packages / "humanize-4.14.0.dist-info"
    (site_packages / HUMANIZE_DIST_INFO).rename(older_dist_info)
    (older_dist_info / "RECORD").unlink()

    _python_phase, pip_runs = provision(
        tmp_path, monkeypatch, exit_codes=[0, 0], watched=older_dist_info,
    )

    assert pip_runs.watched_was_there[0] is False


def test_a_dist_info_that_cannot_be_removed_fails_the_install_without_running_pip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(plugin_venv.shutil, "rmtree", _refuse_removal)
    dist_info = healthy_venv(tmp_path) / SITE_PACKAGES / HUMANIZE_DIST_INFO
    (dist_info / "RECORD").unlink()

    python_phase, pip_runs = provision(tmp_path, monkeypatch, exit_codes=[], watched=dist_info)

    install = python_phase["items"][-1]
    assert pip_runs.commands == []
    assert (install["label"], install["ok"]) == ("install requirements (offline)", False)
    assert install["output"].startswith("PermissionError: Operation not permitted")


def test_a_dist_info_no_baked_wheel_names_is_left_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    venv_path = healthy_venv(tmp_path)
    install_distribution(venv_path, "pip-24.0.dist-info", {"pip/__init__.py": b"24.0"})
    pip_dist_info = venv_path / SITE_PACKAGES / "pip-24.0.dist-info"
    (pip_dist_info / "RECORD").unlink()

    _python_phase, pip_runs = provision(
        tmp_path, monkeypatch, exit_codes=[0], watched=pip_dist_info,
    )

    assert pip_runs.watched_was_there == [True]
    assert pip_dist_info.is_dir()


def test_a_dist_info_reached_through_a_link_out_of_the_venv_is_left_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The drop deletes as root, so a site-packages linked elsewhere must not take that tree."""
    site_packages = healthy_venv(tmp_path) / SITE_PACKAGES
    elsewhere = tmp_path / "elsewhere-site-packages"
    site_packages.rename(elsewhere)
    site_packages.symlink_to(elsewhere)
    (elsewhere / HUMANIZE_DIST_INFO / "RECORD").unlink()

    _python_phase, pip_runs = provision(
        tmp_path, monkeypatch, exit_codes=[0, 0], watched=elsewhere / HUMANIZE_DIST_INFO,
    )

    assert pip_runs.watched_was_there[0] is True
    assert (elsewhere / HUMANIZE_DIST_INFO).is_dir()


def test_a_dist_info_linked_from_inside_the_venv_loses_the_link_not_its_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    venv_path = healthy_venv(tmp_path)
    linked_dist_info = venv_path / SITE_PACKAGES / HUMANIZE_DIST_INFO
    target = venv_path / "kept" / HUMANIZE_DIST_INFO
    target.parent.mkdir()
    linked_dist_info.rename(target)
    linked_dist_info.symlink_to(target)
    (target / "RECORD").unlink()

    _python_phase, pip_runs = provision(
        tmp_path, monkeypatch, exit_codes=[0, 0], watched=linked_dist_info,
    )

    assert pip_runs.watched_was_there[0] is False
    assert target.is_dir()
