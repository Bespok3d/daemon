# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hand the ownership of a patched file over to the plugin taking it on, so the new owner holds the
file's true original and the plugins that patched it before stop holding a copy of it.

A plugin that takes over a file another plugin patches today needs that file's STOCK original as its
baseline: capturing the live file would capture the other plugin's changes and bake them in forever.
The record of who patches what is on the printer, in the installed manifests (`patch_owners` reads
it). The original is the live file with those plugins' patches taken off (`live_original`), never a
kept copy as it is: after a firmware update a kept copy is the old firmware's file. The old owners'
copies of that file are dropped once the new owner's install has SETTLED ok, never at adopt time:
one file, one owner in the end, and until the install settles both ends of the hand-over are kept so
a failure anywhere after adopt leaves every plugin the way back to stock it had before.

Idempotent by state, with no marker file: a plugin that already holds the file is already its owner,
so a second run finds nothing to adopt and changes nothing.
"""

from pathlib import Path

from .. import jinni_client
from ..intent import normalize_install
from ..results import item, phase
from .baseline import kept_original, stock_copies, unix_line_bytes
from .live_original import original_of_the_live_file
from .manifest import readable_manifest
from .patch_owners import kept_copies_of, owners_and_unreadable, patched_targets
from .user_vars import load_user_vars
from .wiring_record import forget_written_file

LIVE_FILE = "the live file"
NO_STOCK_ORIGINAL = "no original to adopt: another plugin's changes cannot be taken off the live file"  # noqa: E501
UNREADABLE_NEIGHBOUR = "cannot take this file over while {plugins} cannot be read: a plugin whose manifest is torn may be the one holding this file's original"  # noqa: E501


def _original_of(owners: dict[Path, list[Path]], target: str) -> str | None:
    """The original of `target` as the printer runs it now, or None when nothing can be proven, so
    nothing unproven is adopted. An empty live file is never the original: no known patch is on it
    only because there is nothing there to find them in, and adopting it would let a later restore
    blank a file the printer boots from."""
    live = jinni_client.fetch(target) or ""
    if not live:
        return None
    return original_of_the_live_file(live, owners)


def _came_from(owners: dict[Path, list[Path]], target: str, original: str) -> str:
    """The owners whose kept copy is this original, else the live file it was worked out from."""
    holders = [owner.name for owner, copy in kept_copies_of(owners, target).items()
               if unix_line_bytes(copy.read_text(errors="replace")) == unix_line_bytes(original)]
    return ", ".join(holders) or LIVE_FILE


def adopt_patch_ownership(plugin_root: Path, adopter_dir: Path, target: str,
                          vars: dict[str, str]) -> dict:
    """Put the original of `target` in the adopting plugin's own kept copies, reported as one phase
    item. The previous owners keep theirs until this install settles ok (commit_patch_handover), so
    a failure after this point still leaves every plugin its way back to stock. Nothing is adopted
    when no original can be proven."""
    file_name = Path(target).name
    adopted = kept_original(stock_copies(adopter_dir), target)
    if adopted.exists():
        return item(f"{file_name}: already owned", ok=True)
    owners, unreadable = owners_and_unreadable(plugin_root, adopter_dir, target, vars)
    if unreadable:
        return item(f"{file_name}: {UNREADABLE_NEIGHBOUR.format(plugins=', '.join(unreadable))}", ok=False)  # noqa: E501
    original = _original_of(owners, target)
    if original is None:
        return item(f"{file_name}: {NO_STOCK_ORIGINAL}", ok=False)
    adopted.parent.mkdir(parents=True, exist_ok=True)
    adopted.write_text(original)
    return item(f"{file_name}: adopted from {_came_from(owners, target, original)}", ok=True)


def adoption_phase(plugin_root: Path, adopter_dir: Path, patches: list[dict],
                   vars: dict[str, str]) -> dict:
    """Take ownership of every file this install patches, as one phase of the install. It runs for
    every patching plugin and on every install and update, never as a one-off migration step, so a
    printer that had a file to take over and a printer that never did both end up the same."""
    items = [adopt_patch_ownership(plugin_root, adopter_dir, target, vars)
             for target in patched_targets(patches, vars)]
    return phase("adopt", "Patch ownership", items)


def commit_patch_handover(plugin_dir: Path, vars: dict[str, str]) -> None:
    """Now that this plugin's install has SETTLED ok, take the old owners' copies of the files it
    took over. One file, one owner, and the owner is the one whose patches are live on the printer.

    Until this runs both ends of the handover are kept, so an install that fails anywhere after
    adopt leaves every plugin exactly the way back to stock it had before. Committing at adopt time
    instead left three plugins on the bench with no original at all: the adopter's copy went with
    its failed install, and theirs had already been taken.

    An old owner's wiring record is told as well, so the off-host escape hatch stops pointing at a
    copy that is no longer there."""
    manifest = readable_manifest(plugin_dir)
    if manifest is None:
        return
    full_vars = {**vars, **load_user_vars(plugin_dir)}
    ops = normalize_install(manifest.get("install", {}), jinni_client.variant_facts())
    for target in patched_targets(ops["patches"], full_vars):
        _hand_one_file_over(plugin_dir, target, full_vars)


def _hand_one_file_over(plugin_dir: Path, target: str, vars: dict[str, str]) -> None:
    adopted = kept_original(stock_copies(plugin_dir), target)
    if not adopted.is_file() or not adopted.read_text(errors="replace"):
        return
    owners, _unreadable = owners_and_unreadable(plugin_dir.parent, plugin_dir, target, vars)
    for owner, copy in kept_copies_of(owners, target).items():
        _let_the_old_owner_go(owner, copy, target)


def _let_the_old_owner_go(owner: Path, copy: Path, target: str) -> None:
    """Drop one old owner's copy of a file the new owner now holds, and tell its wiring record so it
    stops pointing at a copy that is gone.

    A printer that will not take either write (no room left on /userdata, a read-only mount) KEEPS
    that owner's copy instead: the install or the recovery that ran this has already succeeded, the
    new owner already holds the original, and so the printer's way back to stock is safe either way.
    Raising here would fail work that worked, and inside a recovery it would abandon every plugin
    still queued behind this one. The record is only rewritten after the copy is really gone, so the
    two never disagree about whether that copy is still there."""
    try:
        copy.unlink()
        forget_written_file(owner, target)
    except OSError:
        return
