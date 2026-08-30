# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Put a plugin's patched files back to stock when its manifest is gone.

Uninstall normally reads the manifest to learn which files the plugin patched. A manifest lost to a
power cut mid write leaves no such list, and the kept originals under `patches_orig/` are the only
record of what those files looked like before the plugin touched them: they go into the bin with the
plugin directory, and the printer carries the patched file for good. The kept copies answer the
question themselves, because each one is filed under the path of the file it was taken from.
"""

from pathlib import Path

from .baseline import WORK_COPY_SUFFIX, stock_copies
from .patch_reversion import restore_original_files


def _target_of(orig_dir: Path, kept_path: Path) -> str | None:
    """The device path a kept original was taken from, read back out of where it is filed, or None
    when the copy carries no path to read: a copy sitting directly in the kept-copies root was filed
    by an older daemon under the bare file name, and a guessed path would put stock content over a
    file this plugin never patched."""
    filed_at = kept_path.relative_to(orig_dir)
    if filed_at.parent == Path("."):
        return None
    return "/" + str(filed_at)


def targets_with_a_kept_original(orig_dir: Path) -> list[str]:
    """Every device path this plugin holds the stock original of, in path order. A leftover working
    copy is not an original: it is the scratch file a patch run was building when it died."""
    kept_files = sorted(path for path in orig_dir.rglob("*")
                        if path.is_file() and WORK_COPY_SUFFIX not in path.name)
    targets = (_target_of(orig_dir, kept_path) for kept_path in kept_files)
    return [target for target in targets if target is not None]


def restore_originals_without_manifest(plugin_dir: Path) -> None:
    """Put every file this plugin patched back to the original it kept, with no manifest to say
    which files those were. Restoring goes through the same write as the manifest route, so an empty
    or missing copy is left alone there rather than blanking a file the printer boots from."""
    orig_dir = stock_copies(plugin_dir)
    if not orig_dir.is_dir():
        return
    restore_original_files(targets_with_a_kept_original(orig_dir), orig_dir)
