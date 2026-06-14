"""Placement: directories, file modes, and the symlink family.

A plugin integrates by symlink only (the isolation invariant). When a symlink would shadow a stock
file or directory, the pristine original is moved into the plugin-owned `symlink_orig/` backup the
first time, so teardown can restore the firmware exactly. A symlink or overlay whiteout in the way
is just cleared, never saved.
"""

import shutil
from pathlib import Path

from ..results import item as _item
from ..results import phase as _phase
from .user_vars import expand

_SYMLINK_ORIG_DIR = "symlink_orig"


def apply_modes(plugin_dir: Path, files: list[dict]) -> dict:
    items: list[dict] = []
    for entry in files:
        path = plugin_dir / entry["path"]
        if path.exists():
            try:
                path.chmod(int(entry["mode"], 8))
                items.append(_item(f"{entry['path']} → {entry['mode']}", ok=True))
            except Exception as exc:
                items.append(_item(f"{entry['path']}: {exc}", ok=False))
    return _phase("modes", "File modes", items)


def create_dirs(dirs: list[str], vars: dict[str, str]) -> dict:
    items: list[dict] = []
    for directory in dirs:
        expanded = expand(directory, vars)
        try:
            Path(expanded).mkdir(parents=True, exist_ok=True)
            items.append(_item(expanded, ok=True))
        except Exception as exc:
            items.append(_item(f"{expanded}: {exc}", ok=False))
    return _phase("dirs", "Directories", items)


def _symlink_backup_path(plugin_dir: Path, destination: Path) -> Path:
    key = destination.as_posix().strip("/").replace("/", "__") or "root"
    return plugin_dir / _SYMLINK_ORIG_DIR / key


def _clear_existing_destination(destination: Path) -> None:
    if destination.is_symlink():
        destination.unlink()
        return
    if destination.is_dir():
        shutil.rmtree(destination)
        return
    if destination.exists():
        destination.unlink()


def _is_stock_original(path: Path) -> bool:
    """A real dir/file (the stock original worth preserving), not a symlink or overlay whiteout."""
    return (path.is_dir() or path.is_file()) and not path.is_symlink()


def _displace_existing_destination(destination: Path, backup: Path) -> None:
    """Make room for our symlink while preserving any stock original so teardown can restore it.
    A real dir/file is MOVED to the plugin-owned backup the first time only (pristine original
    wins over a regenerated copy); a symlink or overlay whiteout is just cleared, never saved."""
    if not _is_stock_original(destination) or backup.exists():
        _clear_existing_destination(destination)
        return
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(destination), str(backup))


def replace_with_symlink(source: Path, destination: Path, backup: Path | None = None) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if backup is None:
        _clear_existing_destination(destination)
    else:
        _displace_existing_destination(destination, backup)
    destination.symlink_to(source)


def _create_one_symlink(link: dict, plugin_dir: Path, vars: dict[str, str]) -> dict:
    source = (plugin_dir / link["from"]).resolve()
    destination = Path(expand(link["to"], vars))
    backup = _symlink_backup_path(plugin_dir, destination)
    label = f"{link['from']} → {destination}"
    try:
        replace_with_symlink(source, destination, backup)
    except Exception as exc:
        return _item(f"{label}: {exc}", ok=False)
    return _item(label, ok=True)


def create_symlinks(symlinks: list[dict], plugin_dir: Path, vars: dict[str, str]) -> dict:
    items = [_create_one_symlink(link, plugin_dir, vars) for link in symlinks]
    return _phase("symlinks", "Symlinks", items)


def _restore_one_symlink(link: dict, plugin_dir: Path, vars: dict[str, str]) -> None:
    destination = Path(expand(link["to"], vars))
    backup = _symlink_backup_path(plugin_dir, destination)
    if destination.is_symlink():
        destination.unlink()
    if backup.exists() and not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(backup), str(destination))


def remove_plugin_symlinks(symlinks: list[dict], plugin_dir: Path, vars: dict[str, str]) -> None:
    for link in symlinks:
        _restore_one_symlink(link, plugin_dir, vars)
