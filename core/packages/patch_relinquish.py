# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Put back the files a plugin used to patch and no longer does, in the same install that stops
patching them.

A plugin hands a file to the base layer by shipping a version that no longer patches it. The kept
stock copy is the only record of what that file looked like before, and it lives in the plugin that
is giving the file up, so the file has to go back to stock WHILE that copy is still held. Left to a
later run there is nothing to put back from: the plugin no longer declares the patch, so no one can
tell the patched file from an original.

The kept copies are the record of what this plugin patched before, so nothing needs the old manifest
to still be on the printer. Each copy is written back over its target and only then dropped: a copy
released before the file it describes is safely back is an original nobody can recover.
"""

from pathlib import Path

from .. import jinni_client
from ..results import item, phase
from .baseline import WORK_COPY_SUFFIX, stock_copies
from .patch_owners import patched_targets

DIRECTORY_AND_FILE_NAME = 2


def _target_of(kept_path: Path, orig_dir: Path) -> str | None:
    """The device file a kept copy is a copy of. The copies mirror the tree they were taken from,
    so the path under the copies directory IS the target's path. A copy sitting straight in that
    directory is a printer patched by an early daemon that keyed its copies by bare file name: the
    name alone does not say which file on the printer it came from, so it is left alone rather than
    written back over a guess."""
    mirrored = kept_path.relative_to(orig_dir)
    if len(mirrored.parts) < DIRECTORY_AND_FILE_NAME:
        return None
    return f"/{mirrored}"


def _kept_copies(orig_dir: Path) -> list[Path]:
    """Every stock original this plugin holds, leaving out the scratch copies the patch run builds
    its output on."""
    if not orig_dir.is_dir():
        return []
    return sorted(kept_path for kept_path in orig_dir.rglob("*")
                  if kept_path.is_file() and not kept_path.name.endswith(WORK_COPY_SUFFIX))


def _put_back(plugin_dir: Path, target: str, kept_path: Path) -> dict:
    """Write one file back to stock and release the copy of it. An empty copy is left alone, copy
    and all: it was torn mid capture, and writing it back would blank a file the printer boots
    from."""
    file_name = Path(target).name
    stock_text = kept_path.read_text(errors="replace")
    if not stock_text:
        return item(f"{file_name}: left as it is, the kept copy is empty", ok=True)
    written = jinni_client.write_files(str(plugin_dir), [{"path": target, "content": stock_text}])
    if not written[0].ok:
        return item(f"{file_name}: not put back", ok=False, output=written[0].output)
    kept_path.unlink()
    return item(f"{file_name}: put back", ok=True)


def _copies_given_up(orig_dir: Path, still_patched: set[str]) -> list[tuple[str, Path]]:
    """Each kept copy of a file this plugin no longer patches, with the file it belongs to."""
    named = [(_target_of(kept_path, orig_dir), kept_path) for kept_path in _kept_copies(orig_dir)]
    return [(target, kept_path) for target, kept_path in named
            if target is not None and target not in still_patched]


def relinquish_phase(plugin_dir: Path, patches: list[dict], vars: dict[str, str]) -> dict:
    """Give up every file this plugin held a stock original of and no longer patches, as one phase
    of its install. It runs on every install and update of every plugin, so a plugin that stops
    patching a file always leaves that file stock, whichever plugin takes it on and whenever."""
    orig_dir = stock_copies(plugin_dir)
    given_up = _copies_given_up(orig_dir, set(patched_targets(patches, vars)))
    items = [_put_back(plugin_dir, target, kept_path) for target, kept_path in given_up]
    return phase("relinquish", "Files put back", items)
