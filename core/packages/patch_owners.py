# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Who patches a given file on this printer today, and which of them still hold its original.

The record of that is on the printer itself, in the installed plugins' own manifests and kept
copies, so this reads it rather than trusting anything a package says about its neighbours. Moving
the ownership of a file from one plugin to another is `patch_handover`'s.
"""

from pathlib import Path

from .. import jinni_client
from ..intent import normalize_install
from .baseline import kept_original, stock_copies
from .manifest import installed_manifest_dirs, readable_manifest
from .user_vars import expand, load_user_vars


def _fragments_against(plugin_dir: Path, manifest: dict, target: str, vars: dict[str, str],
                       facts: dict[str, str]) -> list[Path]:
    """The diffs this plugin patches `target` with, in the order it applies them."""
    ops = normalize_install(manifest.get("install", {}), facts)
    full_vars = {**vars, **load_user_vars(plugin_dir)}
    return [plugin_dir / patch_def["patch"] for patch_def in ops["patches"]
            if expand(patch_def["file"], full_vars) == target]


def owners_and_unreadable(plugin_root: Path, adopter_dir: Path, target: str,
                          vars: dict[str, str]) -> tuple[dict[Path, list[Path]], list[str]]:
    """Every installed plugin that patches `target` today mapped to the diffs it applies to it, and
    beside it the plugins whose own manifest could not be read at all. The adopting plugin is left
    out of both: it is the one taking the file over."""
    facts = jinni_client.variant_facts()
    others = [plugin_dir for plugin_dir in installed_manifest_dirs(plugin_root)
              if plugin_dir != adopter_dir]
    read = {plugin_dir: readable_manifest(plugin_dir) for plugin_dir in others}
    patching = {plugin_dir: _fragments_against(plugin_dir, manifest, target, vars, facts)
                for plugin_dir, manifest in read.items() if manifest is not None}
    owners = {plugin_dir: fragments for plugin_dir, fragments in patching.items() if fragments}
    return owners, [plugin_dir.name for plugin_dir, manifest in read.items() if manifest is None]


def kept_copies_of(owners: dict[Path, list[Path]], target: str) -> dict[Path, Path]:
    """The owners that still hold this file's original, and the copy each one holds."""
    holding = {owner: kept_original(stock_copies(owner), target) for owner in owners}
    return {owner: copy for owner, copy in holding.items() if copy.exists()}


def patched_targets(patches: list[dict], vars: dict[str, str]) -> list[str]:
    """Each file an install patches, once, in first-appearance order: several fragments for one file
    share one owner, so the file is taken over once."""
    return list(dict.fromkeys(expand(patch_def["file"], vars) for patch_def in patches))
