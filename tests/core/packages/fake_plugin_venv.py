# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A made-up plugin venv laid out the way pip leaves one, shared by the venv health and repair
tests so both check the same two installed distributions, and a provision of it with pip faked."""
import hashlib
import subprocess
from pathlib import Path

import pytest

from core.packages import plugin_venv
from core.wheel_record import encoded_digest

HUMANIZE_WHEEL = "humanize-4.15.0-py3-none-any.whl"
YAML_WHEEL = "PyYAML-6.0.1-cp311-cp311-linux_aarch64.whl"
HUMANIZE_DIST_INFO = "humanize-4.15.0.dist-info"
SITE_PACKAGES = "lib/python3.11/site-packages"
_HUMANIZE_FILES = {"humanize/__init__.py": b"VERSION = '4.15.0'\n", "../../../bin/humanize": b"#!"}


def recorded_digest(content: bytes) -> str:
    return encoded_digest(hashlib.sha256(content).digest())


def install_distribution(
    venv_path: Path, dist_info_dirname: str, files: dict[str, bytes],
) -> Path:
    """Lay a distribution out the way pip leaves it: its files, and a RECORD naming each one with
    the unhashed rows pip adds. Answers the site-packages dir it went into."""
    site_packages = venv_path / SITE_PACKAGES
    dist_info = site_packages / dist_info_dirname
    dist_info.mkdir(parents=True)
    rows = [f"{path},sha256={recorded_digest(content)},{len(content)}"
            for path, content in files.items()]
    rows += [f"{dist_info_dirname}/RECORD,,", *_bytecode_rows(files)]
    (dist_info / "RECORD").write_text("\n".join(rows) + "\n")
    for path, content in files.items():
        (site_packages / path).parent.mkdir(parents=True, exist_ok=True)
        (site_packages / path).write_bytes(content)
    return site_packages


class RecordingRun:
    """A subprocess.run double that records every command, and whether the watched path was there
    as each one ran, and answers each with the next of the given exit codes."""

    def __init__(self, exit_codes: list[int], watched: Path) -> None:
        self.commands: list[list[str]] = []
        self.watched_was_there: list[bool] = []
        self.exit_codes = exit_codes
        self.watched = watched

    def __call__(self, command: list[str], **_options: object) -> object:
        self.commands.append(command)
        self.watched_was_there.append(self.watched.exists())
        exit_code = self.exit_codes[len(self.commands) - 1]
        return subprocess.CompletedProcess(command, exit_code, b"", b"")


def provision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exit_codes: list[int], watched: Path,
) -> tuple[dict, RecordingRun]:
    """Provision a plugin baking both wheels into the venv at `tmp_path/venv-plugins/notifier`,
    each pip run answering with the next exit code."""
    recorder = RecordingRun(exit_codes, watched)
    monkeypatch.setattr(plugin_venv.subprocess, "run", recorder)
    python_phase = plugin_venv.provision_venv_phase(
        plugin_with_baked_wheels(tmp_path), {"BESPOK3D": str(tmp_path)},
    )
    assert python_phase is not None
    return python_phase, recorder


def plugin_with_baked_wheels(tmp_path: Path) -> Path:
    plugin_dir = tmp_path / "plugins/notifier"
    (plugin_dir / "files/wheels").mkdir(parents=True)
    (plugin_dir / "requirements.txt").write_text("humanize>=4.9.0\nPyYAML\n")
    (plugin_dir / "files/wheels" / HUMANIZE_WHEEL).write_bytes(b"wheel")
    (plugin_dir / "files/wheels" / YAML_WHEEL).write_bytes(b"wheel")
    return plugin_dir


def healthy_venv(tmp_path: Path) -> Path:
    venv_path = tmp_path / "venv-plugins/notifier"
    install_distribution(venv_path, HUMANIZE_DIST_INFO, _HUMANIZE_FILES)
    install_distribution(venv_path, "PyYAML-6.0.1.dist-info", {"yaml/__init__.py": b"6.0.1"})
    return venv_path


def _bytecode_rows(files: dict[str, bytes]) -> list[str]:
    """pip compiles each module after install and records the .pyc with no digest."""
    modules = [Path(path) for path in files if path.endswith(".py")]
    return [f"{module.parent}/__pycache__/{module.stem}.cpython-311.pyc,," for module in modules]
