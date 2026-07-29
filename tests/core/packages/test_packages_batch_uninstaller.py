# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The batched uninstall lives in core/packages/batch_uninstaller.py: remove several plugins with
their core-service restart deferred, deduped, and run once, isolating one plugin's removal failure
and refusing a plugin still depended on by an installed plugin outside the selection unless cascade.
"""

import json
import subprocess as sp
from pathlib import Path

import pytest

from core import packages
from core.packages import batch_uninstaller

MP = pytest.MonkeyPatch


def _write_plugin(
    plugin_root: Path,
    plugin_id: str,
    *,
    provides: list[str] | None = None,
    depends: list[str] | None = None,
    restart: list[str] | None = None,
) -> None:
    plugin_dir = plugin_root / plugin_id
    plugin_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": plugin_id,
        "version": "0.1.0",
        "provides": provides or [],
        "depends": depends or [],
        "install": {"restart": restart or []},
    }
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest))


class _FakeResult:
    returncode = 0
    stdout = b""
    stderr = b""


def test_uninstall_batch_empty_returns_empty(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    assert packages.uninstall_batch([], {}) == []


def test_uninstall_batch_removes_each_and_restarts_once(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    _write_plugin(tmp_path, "alpha", restart=["klipper"])
    _write_plugin(tmp_path, "beta", restart=["klipper"])
    ran: list[object] = []

    def fake_run(cmd: object, **_kw: object) -> _FakeResult:
        ran.append(cmd)
        return _FakeResult()

    monkeypatch.setattr(sp, "run", fake_run)

    results = packages.uninstall_batch(["alpha", "beta"], {})

    assert {entry["plugin_id"] for entry in results if entry["ok"]} >= {"alpha", "beta"}
    assert not (tmp_path / "alpha").exists()
    assert not (tmp_path / "beta").exists()
    assert ran.count("/etc/init.d/S60klipper restart") == 1


def test_uninstall_batch_isolates_a_failing_removal(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    _write_plugin(tmp_path, "good")
    _write_plugin(tmp_path, "bad")
    real_remove = batch_uninstaller.remove_with_dependents

    def remove(plugin_root: Path, plugin_id: str, vars: dict[str, str], removed: list[str]) -> None:
        if plugin_id == "bad":
            raise RuntimeError("kaboom")
        real_remove(plugin_root, plugin_id, vars, removed)

    monkeypatch.setattr(batch_uninstaller, "remove_with_dependents", remove)

    results = packages.uninstall_batch(["good", "bad"], {})

    by_id = {entry["plugin_id"]: entry for entry in results}
    assert by_id["good"]["ok"] is True
    assert by_id["bad"]["ok"] is False
    assert "kaboom" in by_id["bad"]["reason"]
    assert not (tmp_path / "good").exists()
    assert (tmp_path / "bad").exists()


def test_uninstall_batch_refuses_an_external_dependent(tmp_path: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    _write_plugin(tmp_path, "provider", provides=["svc"])
    _write_plugin(tmp_path, "consumer", depends=["svc@>=1.0"])

    with pytest.raises(packages.DependentsError) as excinfo:
        packages.uninstall_batch(["provider"], {})

    assert excinfo.value.dependents == ["consumer"]
    assert (tmp_path / "provider").exists()


def test_uninstall_batch_cascade_removes_external_dependents(
    tmp_path: Path, monkeypatch: MP
) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    _write_plugin(tmp_path, "provider", provides=["svc"])
    _write_plugin(tmp_path, "consumer", depends=["svc@>=1.0"])

    packages.uninstall_batch(["provider"], {}, cascade=True)

    assert not (tmp_path / "provider").exists()
    assert not (tmp_path / "consumer").exists()


def test_uninstall_batch_allows_a_dependent_inside_the_selection(
    tmp_path: Path, monkeypatch: MP
) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    _write_plugin(tmp_path, "provider", provides=["svc"])
    _write_plugin(tmp_path, "consumer", depends=["svc@>=1.0"])

    results = packages.uninstall_batch(["provider", "consumer"], {})

    assert {entry["plugin_id"] for entry in results} == {"provider", "consumer"}
    assert not (tmp_path / "provider").exists()
    assert not (tmp_path / "consumer").exists()
