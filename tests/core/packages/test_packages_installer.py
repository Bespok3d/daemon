# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A fresh install lives in core/packages/installer.py, the config-only reconfigure in
reconfigurer.py, and the batched update in updater.py; the two install-shaped paths (install and
batched update) share ONE phase runner (`apply_install_deferred`), which install drives live (a
notify callback) and the batched update drives silently (the default no-op)."""

from pathlib import Path

from core import packages
from core.packages import installer, reconfigurer, updater


def test_installer_module_exposes_the_op_workers() -> None:
    assert callable(installer.run_install)
    assert callable(reconfigurer.run_reconfigure)
    assert callable(updater.run_update_batch)


def test_phase_listener_is_reexported_from_the_facade() -> None:
    assert packages.PhaseListener is installer.PhaseListener


def test_apply_install_deferred_runs_every_phase_and_defers_the_restart(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plug"
    plugin_dir.mkdir()
    manifest = {"name": "plug", "install": {}, "files": []}

    phases, deferred = installer.apply_install_deferred(tmp_path, plugin_dir, manifest, {})

    assert [phase["id"] for phase in phases] == [
        "modes", "dirs", "templates", "services", "kmodules", "symlinks", "patches", "ownership",
        "kmodule-load", "start",
    ]
    assert deferred == []


def test_apply_install_deferred_announces_each_phase_to_the_notify(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plug"
    plugin_dir.mkdir()
    manifest = {"name": "plug", "install": {}, "files": []}
    seen: list[dict] = []

    phases, _deferred = installer.apply_install_deferred(
        tmp_path, plugin_dir, manifest, {}, seen.append,
    )

    assert [phase["id"] for phase in seen] == [phase["id"] for phase in phases]
