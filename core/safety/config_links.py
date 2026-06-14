"""Self-heal the bespok3d include dirs: drop dead .cfg symlinks and bounce Moonraker.

A symlink under config/bespok3d/* whose target no longer exists is junk left from an earlier
uninstall, and it makes Klipper/Moonraker fail to start. The restart-batch verify cycle prunes these
and restarts Moonraker once more when its first restart left it down.
"""
import subprocess
from pathlib import Path

from jinni.loader import get_jinni

from ..intent import RESTART_HOOKS
from ..shell import start_env


def _config_link_dirs() -> list[Path]:
    """The bespok3d include dirs where plugin .cfg symlinks live (config/bespok3d/*)."""
    try:
        paths = get_jinni().paths()
    except Exception:  # noqa: BLE001 - missing jinni on a non-printer host: nothing to prune
        return []
    keys = ("BESPOK3D_KLIPPER", "BESPOK3D_MOONRAKER")
    return [Path(paths[key]) for key in keys if paths.get(key)]


def _dead_links_in(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return [entry for entry in sorted(directory.iterdir())
            if entry.is_symlink() and not entry.exists()]


def prune_dead_config_links(dirs: list[Path] | None = None) -> list[str]:
    """Remove symlinks under the bespok3d include dirs whose target no longer exists. A dead include
    link makes Klipper/Moonraker fail to start and is always junk left from an earlier uninstall, so
    removing it is safe. Returns the paths removed. `dirs` is injectable for tests."""
    removed: list[str] = []
    for directory in _config_link_dirs() if dirs is None else dirs:
        for dead_link in _dead_links_in(directory):
            dead_link.unlink()
            removed.append(str(dead_link))
    return removed


def restart_moonraker() -> None:
    subprocess.run(
        RESTART_HOOKS["moonraker"], shell=True, capture_output=True, check=False, env=start_env()
    )
