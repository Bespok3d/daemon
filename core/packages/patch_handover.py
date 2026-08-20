# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hand the ownership of a patched file over to the plugin taking it on, so the new owner holds the
file's true original and the plugins that patched it before stop holding a copy of it.

A plugin that takes over a file another plugin patches today needs that file's STOCK original as its
baseline: capturing the live file would capture the other plugin's changes and bake them in forever.
The record of who patches what is on the printer, in the installed manifests, so this reads it and
adopts the one kept copy that no known patch has been applied to. When no kept copy qualifies, the
known patches are reversed back off the live file to recover the original. The old owners' copies of
that file are dropped once the new owner holds it: one file, one owner, so a later restore can only
write back the one original.

Idempotent by state, with no marker file: a plugin that already holds the file is already its owner,
so a second run finds nothing to adopt and changes nothing.
"""

from pathlib import Path

from .. import jinni_client
from ..intent import normalize_install
from ..results import item
from .baseline import is_stock, kept_original, stock_copies, without_patches
from .manifest import installed_manifest_dirs, manifest_at
from .user_vars import expand, load_user_vars

NO_STOCK_ORIGINAL = "no original to adopt: every kept copy is patched and the live file cannot be reversed"  # noqa: E501


def _fragments_against(plugin_dir: Path, target: str, vars: dict[str, str],
                       facts: dict[str, str]) -> list[Path]:
    """The diffs this plugin patches `target` with, in the order it applies them."""
    ops = normalize_install(manifest_at(plugin_dir).get("install", {}), facts)
    full_vars = {**vars, **load_user_vars(plugin_dir)}
    return [plugin_dir / patch_def["patch"] for patch_def in ops["patches"]
            if expand(patch_def["file"], full_vars) == target]


def _current_owners(plugin_root: Path, adopter_dir: Path, target: str,
                    vars: dict[str, str]) -> dict[Path, list[Path]]:
    """Every installed plugin that patches `target` today, mapped to the diffs it applies to it.
    The adopting plugin is left out: it is the one taking the file over."""
    facts = jinni_client.variant_facts()
    others = [plugin_dir for plugin_dir in installed_manifest_dirs(plugin_root)
              if plugin_dir != adopter_dir]
    patching = {plugin_dir: _fragments_against(plugin_dir, target, vars, facts)
                for plugin_dir in others}
    return {plugin_dir: fragments for plugin_dir, fragments in patching.items() if fragments}


def _stock_from_kept_copies(owners: dict[Path, list[Path]], target: str,
                            known_fragments: list[Path]) -> str | None:
    """The first kept copy that no known patch is on: that one is the true original."""
    kept = [kept_original(stock_copies(plugin_dir), target) for plugin_dir in owners]
    held = (copy_path.read_text(errors="replace") for copy_path in kept if copy_path.exists())
    return next((text for text in held if is_stock(text, known_fragments)), None)


def _stock_from_the_live_file(target: str, known_fragments: list[Path]) -> str | None:
    """The live file when no known patch is on it, else the live file with the known patches
    reversed back off it. None when neither holds, so nothing unproven is adopted as the
    original. An empty live file is never the original: no known patch is on it only because there
    is nothing there to find them in, and adopting it would let a later restore blank a file the
    printer boots from."""
    live = jinni_client.fetch(target)
    if not live:
        return None
    if is_stock(live, known_fragments):
        return live
    return without_patches(live, known_fragments)


def _drop_old_copies(owners: dict[Path, list[Path]], target: str) -> list[str]:
    """Drop each old owner's kept copy of the file, naming the plugins handed over. A copy left
    behind is a second original, and a later restore could write it back over the new owner's."""
    dropping = {plugin_dir: kept_original(stock_copies(plugin_dir), target)
                for plugin_dir in owners}
    handed_over = [plugin_dir for plugin_dir, copy_path in dropping.items() if copy_path.exists()]
    for plugin_dir in handed_over:
        dropping[plugin_dir].unlink()
    return [plugin_dir.name for plugin_dir in handed_over]


def adopt_patch_ownership(plugin_root: Path, adopter_dir: Path, target: str,
                          vars: dict[str, str]) -> dict:
    """Put the original of `target` in the adopting plugin's own kept copies and drop the previous
    owners' copies of it, reported as one phase item. Nothing is dropped when no original can be
    established: a file whose original cannot be proven keeps every copy the printer holds."""
    file_name = Path(target).name
    adopted = kept_original(stock_copies(adopter_dir), target)
    if adopted.exists():
        return item(f"{file_name}: already owned", ok=True)
    owners = _current_owners(plugin_root, adopter_dir, target, vars)
    known_fragments = [fragment for fragments in owners.values() for fragment in fragments]
    kept_stock = _stock_from_kept_copies(owners, target, known_fragments)
    stock_text = kept_stock if kept_stock is not None else _stock_from_the_live_file(target, known_fragments)  # noqa: E501
    if stock_text is None:
        return item(f"{file_name}: {NO_STOCK_ORIGINAL}", ok=False)
    adopted.parent.mkdir(parents=True, exist_ok=True)
    adopted.write_text(stock_text)
    handed_over = _drop_old_copies(owners, target)
    return item(f"{file_name}: adopted from {', '.join(handed_over) or 'the live file'}", ok=True)
