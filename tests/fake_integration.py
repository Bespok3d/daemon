# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The in-process integration teardown a fake jinni performs: prune dead include links, remove the
bespok3d include lines, and prune the bespok3d config dir. Mirrors the jinni's integration facet in
plain stdlib (the daemon test suite cannot import the jinni runtime). The fake's verb methods
delegate here.
"""
from pathlib import Path


def _dead_links(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return [entry for entry in sorted(directory.iterdir())
            if entry.is_symlink() and not entry.exists()]


def _prune_tree(root: Path) -> None:
    if not root.is_dir():
        return
    for child in sorted(root.iterdir()):
        if child.is_symlink():
            child.unlink()
        elif child.is_dir():
            _prune_tree(child)
    if not any(root.iterdir()):
        root.rmdir()


def prune_dead_links(include_dirs: list[str]) -> list[str]:
    removed: list[str] = []
    for directory in include_dirs:
        for dead in _dead_links(Path(directory)):
            dead.unlink()
            removed.append(str(dead))
    return removed


def remove_includes(printer_cfg: str, moonraker_cfg: str) -> None:
    for cfg_path, pattern in ((printer_cfg, "[include bespok3d/klipper"),
                              (moonraker_cfg, "[include bespok3d/moonraker")):
        path = Path(cfg_path)
        if path.exists():
            kept = [ln for ln in path.read_text().splitlines(keepends=True) if pattern not in ln]
            path.write_text("".join(kept))


def prune_config_dir(bespok3d_klipper: str) -> None:
    config_dir = Path(bespok3d_klipper).parent
    if config_dir.name == "bespok3d":
        _prune_tree(config_dir)
