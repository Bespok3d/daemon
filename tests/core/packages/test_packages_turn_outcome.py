# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The live install list learns how each plugin's turn ended from an `outcome` event.

The bug: the list only heard which plugin a batch started and which phases finished, so the app
ticked every row once the batch was done, a plugin left out or switched off included.
"""
from pathlib import Path

import pytest

from core import packages
from core.packages import batch
from core.packages.batch_progress import BatchProgress
from core.packages.batch_rows import settle_after_safety_net
from tests.package_fixtures import package_bytes

MP = pytest.MonkeyPatch
KLIPPER_RESTART = "/etc/init.d/S60klipper restart"


def _package(tmp_path: Path, plugin_id: str, extra: dict) -> Path:
    manifest = {
        "name": plugin_id, "version": "0.1.0",
        "install": {"dirs": [], "symlinks": [], "patches": [], "start": []}, **extra,
    }
    package_path = tmp_path / f"{plugin_id}.b3"
    package_path.write_bytes(package_bytes(manifest, {}))
    return package_path


def _outcomes(published: list[dict]) -> list[tuple[str, bool, bool]]:
    return [(event["plugin_id"], event["ok"], event["skipped"])
            for event in published if event["type"] == "outcome"]


CAMERA_SWITCHED_OFF_ROW = {"plugin_id": "(services)", "ok": False, "skipped": False, "reason": "",
                           "log": [], "auto_deactivated": "camera",
                           "fix_detail": "klipper did not come back"}


def _net_switches_off_camera(_plugin_root: Path, _restarts: list[str], _vars: dict[str, str],
                             _ctx: object) -> dict:
    return CAMERA_SWITCHED_OFF_ROW


def test_a_plugin_left_out_of_the_batch_is_announced_as_skipped(
        tmp_path: Path, plugin_root: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", plugin_root)
    zerotier = _package(tmp_path, "zerotier", {"require": [{"service": "tun"}]})
    camera = _package(tmp_path, "camera", {})
    published: list[dict] = []

    packages.install_batch({}, [zerotier, camera], {}, published.append)

    assert _outcomes(published) == [("zerotier", False, True), ("camera", True, False)]


def test_an_unreadable_package_is_announced_as_failed(
        tmp_path: Path, plugin_root: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", plugin_root)
    broken = tmp_path / "broken.b3"
    broken.write_bytes(b"not a package")
    published: list[dict] = []

    packages.install_batch({}, [broken], {}, published.append)

    assert _outcomes(published) == [("broken", False, False)]


def test_a_plugin_the_net_switches_off_is_announced_again_as_failed(
        tmp_path: Path, plugin_root: Path, monkeypatch: MP) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", plugin_root)
    monkeypatch.setattr(batch, "restart_services", _net_switches_off_camera)
    camera = _package(tmp_path, "camera", {"install": {
        "dirs": [], "symlinks": [], "patches": [], "start": [KLIPPER_RESTART]}})
    published: list[dict] = []

    packages.install_batch({}, [camera], {}, published.append)

    assert _outcomes(published) == [("camera", True, False), ("camera", False, False)]


def test_a_skipped_plugin_the_net_switches_off_is_failed_not_skipped() -> None:
    """A skipped row counts as fine on a recover, so one the net switched off would hide it."""
    stranded_row = {"plugin_id": "camera", "ok": False, "skipped": True, "reason": "", "log": []}
    published: list[dict] = []

    settled = settle_after_safety_net(
        [stranded_row], CAMERA_SWITCHED_OFF_ROW, BatchProgress(published.append))

    assert (settled[0]["ok"], settled[0]["skipped"]) == (False, False)
    assert _outcomes(published) == [("camera", False, False)]
