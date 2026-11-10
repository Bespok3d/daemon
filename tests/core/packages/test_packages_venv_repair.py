# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""An install, update or recover reinstalls only the baked wheels whose venv files are torn,
right after the plain offline install that skipped them as already there."""
from pathlib import Path

import pytest

from tests.core.packages.fake_plugin_venv import (
    HUMANIZE_WHEEL,
    SITE_PACKAGES,
    healthy_venv,
    provision,
)

_INSTALL_LABEL = "install requirements (offline)"
_REPAIR_LABEL = "repair broken requirements (offline)"


def test_only_the_torn_wheel_is_reinstalled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    venv_path = healthy_venv(tmp_path)
    (venv_path / SITE_PACKAGES / "humanize/__init__.py").write_bytes(b"torn")

    python_phase, pip_runs = provision(tmp_path, monkeypatch, exit_codes=[0, 0], watched=venv_path)

    wheels_dir = tmp_path / "plugins/notifier/files/wheels"
    assert pip_runs.commands[-1] == [
        str(venv_path / "bin/pip"), "install", "--no-index", "--no-deps", "--force-reinstall",
        str(wheels_dir / HUMANIZE_WHEEL),
    ]
    assert [step["label"] for step in python_phase["items"]] == [_INSTALL_LABEL, _REPAIR_LABEL]


def test_an_intact_venv_gets_no_repair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    venv_path = healthy_venv(tmp_path)

    python_phase, pip_runs = provision(tmp_path, monkeypatch, exit_codes=[0], watched=venv_path)

    assert len(pip_runs.commands) == 1
    assert [step["label"] for step in python_phase["items"]] == [_INSTALL_LABEL]


def test_a_failed_install_is_not_followed_by_a_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    venv_path = healthy_venv(tmp_path)
    (venv_path / SITE_PACKAGES / "humanize/__init__.py").unlink()

    python_phase, pip_runs = provision(tmp_path, monkeypatch, exit_codes=[1], watched=venv_path)

    assert len(pip_runs.commands) == 1
    assert python_phase["ok"] is False


def test_a_failed_repair_fails_the_python_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A venv still torn after the repair would fail the plugin at its first import, so the
    install says so now."""
    venv_path = healthy_venv(tmp_path)
    (venv_path / SITE_PACKAGES / "humanize/__init__.py").write_bytes(b"torn")

    python_phase, _pip_runs = provision(tmp_path, monkeypatch, exit_codes=[0, 1], watched=venv_path)

    repair = python_phase["items"][-1]
    assert (repair["label"], repair["ok"], python_phase["ok"]) == (_REPAIR_LABEL, False, False)
