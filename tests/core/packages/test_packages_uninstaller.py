"""The uninstall family lives in core/packages/uninstaller.py: remove a plugin (and its installed
dependents, dependents-first) and run the core-service restart hooks the removal declares, so a
deleted [section] or web location actually leaves the running service."""

import json
from pathlib import Path

from core.packages import uninstaller


def _install_manifest(plugin_root: Path, plugin_id: str, restart: list[str]) -> None:
    plugin_dir = plugin_root / plugin_id
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text(
        json.dumps({"name": plugin_id, "install": {"restart": restart}})
    )


def test_uninstaller_module_exposes_run_uninstall() -> None:
    assert callable(uninstaller.run_uninstall)


def test_removal_restart_commands_reads_manifests_and_dedupes_hooks(tmp_path: Path) -> None:
    _install_manifest(tmp_path, "alpha", ["klipper"])
    _install_manifest(tmp_path, "beta", ["klipper", "moonraker"])

    commands = uninstaller._removal_restart_commands(tmp_path, ["alpha", "beta"], {})

    assert commands == [
        "/etc/init.d/S60klipper restart",
        "/etc/init.d/S61moonraker restart",
    ]


def test_removal_restart_commands_skips_an_uninstalled_id(tmp_path: Path) -> None:
    _install_manifest(tmp_path, "alpha", ["moonraker"])

    commands = uninstaller._removal_restart_commands(tmp_path, ["alpha", "ghost"], {})

    assert commands == ["/etc/init.d/S61moonraker restart"]
