# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
import json
from pathlib import Path

import pytest

from core import packages, selfcheck

MP = pytest.MonkeyPatch


def _make_plugin_with_symlink(
    plugin_root: Path,
    plugin_id: str,
    link_path: Path,
    deactivated: bool = False,
) -> Path:
    plugin_dir = plugin_root / plugin_id
    plugin_dir.mkdir(parents=True)
    source_file = plugin_dir / "files" / "mod.py"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("# source\n")
    manifest = {
        "name": plugin_id,
        "install": {
            "symlinks": [{"from": "files/mod.py", "to": str(link_path)}],
        },
    }
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest))
    if deactivated:
        (plugin_dir / "deactivated.json").write_text("{}")
    return plugin_dir


def test_selfcheck_returns_empty_when_no_plugins_installed(
    tmp_path: Path, monkeypatch: MP
) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path / "empty")
    assert selfcheck.run_selfcheck({}) == []


def test_selfcheck_returns_empty_when_every_symlink_is_correct(
    tmp_path: Path, monkeypatch: MP
) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path / "plugins")
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    link_path = tmp_path / "extras" / "mod.py"
    link_path.parent.mkdir()
    plugin_dir = _make_plugin_with_symlink(plugin_root, "good-plugin", link_path)
    link_path.symlink_to((plugin_dir / "files" / "mod.py").resolve())

    assert selfcheck.run_selfcheck({}) == []


def test_selfcheck_reports_missing_symlink(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path / "plugins")
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    link_path = tmp_path / "extras" / "mod.py"
    link_path.parent.mkdir()
    _make_plugin_with_symlink(plugin_root, "missing-plugin", link_path)

    drift = selfcheck.run_selfcheck({})

    assert len(drift) == 1
    assert drift[0]["plugin_id"] == "missing-plugin"
    issues = drift[0]["symlink_issues"]
    assert len(issues) == 1
    assert issues[0]["kind"] == selfcheck.ISSUE_MISSING
    assert issues[0]["link_path"] == str(link_path)


def test_selfcheck_reports_wrong_target(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path / "plugins")
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    link_path = tmp_path / "extras" / "mod.py"
    link_path.parent.mkdir()
    plugin_dir = _make_plugin_with_symlink(plugin_root, "drifted-plugin", link_path)
    rogue_target = tmp_path / "rogue.py"
    rogue_target.write_text("# rogue\n")
    link_path.symlink_to(rogue_target)

    drift = selfcheck.run_selfcheck({})

    assert len(drift) == 1
    issue = drift[0]["symlink_issues"][0]
    assert issue["kind"] == selfcheck.ISSUE_WRONG_TARGET
    assert issue["actual_target"] == str(rogue_target)
    assert issue["expected_target"] == str((plugin_dir / "files" / "mod.py").resolve())


def test_selfcheck_reports_when_path_is_not_a_symlink(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path / "plugins")
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    link_path = tmp_path / "extras" / "mod.py"
    link_path.parent.mkdir()
    _make_plugin_with_symlink(plugin_root, "clobbered-plugin", link_path)
    link_path.write_text("# someone replaced the symlink with a regular file\n")

    drift = selfcheck.run_selfcheck({})

    assert len(drift) == 1
    issue = drift[0]["symlink_issues"][0]
    assert issue["kind"] == selfcheck.ISSUE_NOT_A_SYMLINK


def test_selfcheck_skips_deactivated_plugins(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path / "plugins")
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    link_path = tmp_path / "extras" / "mod.py"
    link_path.parent.mkdir()
    _make_plugin_with_symlink(plugin_root, "deactivated-plugin", link_path, deactivated=True)

    assert selfcheck.run_selfcheck({}) == []


def test_selfcheck_uses_persisted_user_vars(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path / "plugins")
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    plugin_id = "var-plugin"
    plugin_dir = plugin_root / plugin_id
    plugin_dir.mkdir()
    (plugin_dir / "files").mkdir()
    (plugin_dir / "files" / "mod.py").write_text("# src\n")
    extras_dir = tmp_path / "extras"
    extras_dir.mkdir()
    manifest = {
        "name": plugin_id,
        "install": {"symlinks": [{"from": "files/mod.py", "to": "$EXTRAS/mod.py"}]},
    }
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest))
    (plugin_dir / "user_vars.json").write_text(json.dumps({"EXTRAS": str(extras_dir)}))

    drift = selfcheck.run_selfcheck({})

    assert len(drift) == 1
    issue = drift[0]["symlink_issues"][0]
    assert issue["kind"] == selfcheck.ISSUE_MISSING
    assert issue["link_path"] == str(extras_dir / "mod.py")
