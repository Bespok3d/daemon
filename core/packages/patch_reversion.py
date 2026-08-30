# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Putting the files a plugin patched back to the originals it kept.

WHICH files is decided by what the jinni recorded writing for this plugin, never by what its
manifest declares. Those two disagree exactly when it matters: a plugin whose install failed before
its diffs reached the device holds kept originals for files it never wrote, and another plugin's
patches may be live on those files right now. Writing this plugin's idea of stock over them would
strip a plugin the user still has, without a word, on a printer that was working a minute ago.

An empty kept copy is skipped: a copy torn by a power cut mid capture would blank a file the printer
boots from, and leaving the file as it is is what a missing copy already does.
"""

from pathlib import Path

from .. import jinni_client
from . import baseline
from .user_vars import expand
from .wiring_record import written_files


def revert_patched_files(plugin_dir: Path, patches: list[dict], vars: dict[str, str]) -> None:
    """Undo this plugin's patches: put back the original of every file its diffs name and it
    actually wrote."""
    restore_original_files(_written_by_this_plugin(plugin_dir, patches, vars),
                           baseline.stock_copies(plugin_dir))


def _written_by_this_plugin(
    plugin_dir: Path, patches: list[dict], vars: dict[str, str],
) -> list[str]:
    written = written_files(plugin_dir)
    named = (str(Path(expand(patch_def["file"], vars))) for patch_def in patches)
    return [target for target in dict.fromkeys(named) if target in written]


def restore_original_files(targets: list[str], orig_dir: Path) -> None:
    """Write each named file's kept original back over it through the jinni, undoing the patch."""
    plugin_dir = orig_dir.parent
    kept = ((target, baseline.kept_original(orig_dir, target)) for target in dict.fromkeys(targets))
    writes = [{"path": target, "content": copy.read_text(errors="replace")}
              for target, copy in kept if copy.exists()]
    if writes:
        jinni_client.write_files(str(plugin_dir), [write for write in writes if write["content"]])
