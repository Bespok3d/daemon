# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The kept originals of a plugin, settled against the printer's files before they are written back.

After a firmware update a plugin's kept original of a patched file is the OLD firmware's file, and
switching the plugin off or removing it would write it over the new one. So before either, each
kept original becomes the printer's file as it is NOW with this plugin's patches taken off: a user's
own edit and another plugin's patches stay, and the new firmware's lines come back. When the patches
cannot be taken off, the copy is dropped with its undo step and the file is left as it is. A copy an
older daemon kept under a bare file name two patched files share is left alone: it says nothing
about which of them it came from.

Without a firmware update this changes nothing: the file with the plugin's patches taken off IS the
kept original. A failed install or update never settles: its kept copies are fresh, and the file
may hold only part of its patches, so they are the true way back.
"""

import shutil
from pathlib import Path

from .. import jinni_client
from ..intent import normalize_install
from .baseline import kept_original, stock_copies, unix_line_bytes, without_patches
from .manifest import readable_manifest
from .patch_owners import fragments_by_target
from .user_vars import expand, load_user_vars, missing_required_vars, with_declared_defaults
from .wiring_record import forget_written_file, written_files

COPIES_REMOVED_UNCHECKED = "its saved printer files could not be checked and were removed"
_SETTING_PROBE = "a value no setting holds"


def settle_before_switch_off(plugin_dir: Path, vars: dict[str, str], reason: str) -> str:
    """Settle the kept originals of a plugin about to be switched off for `reason`, which comes
    back naming the dropped copies when they could not be checked. A switch-off cannot be refused,
    so a failed check drops the copies instead of stopping it. A torn manifest names no patches, so
    nothing is checked and the copies stay: they cannot be told stale from true."""
    manifest = readable_manifest(plugin_dir)
    if manifest is None:
        return reason
    check_error = settle_or_drop_kept_originals(plugin_dir, manifest, vars)
    if check_error is None:
        return reason
    return f"{reason}; {COPIES_REMOVED_UNCHECKED}: {check_error}"


def settle_or_drop_kept_originals(plugin_dir: Path, manifest: dict,
                                  vars: dict[str, str]) -> str | None:
    """Settle the kept originals, or drop them all when they cannot be checked, returning why."""
    try:
        settle_kept_originals(plugin_dir, manifest, vars)
    except Exception as exc:  # noqa: BLE001 - a check that fails must NOT stop the switch-off
        # Unchecked copies may be the old firmware's files, so none of them is written back.
        drop_kept_originals(plugin_dir)
        return f"{type(exc).__name__}: {exc}"
    return None


def settle_kept_originals(plugin_dir: Path, manifest: dict, vars: dict[str, str]) -> None:
    """Make each kept original the original of the printer's file as it is now, so what writes
    them back next never writes an older firmware's file. Raises when they cannot be checked."""
    if not _holds_kept_copies(plugin_dir):
        return
    settings = {**vars, **with_declared_defaults(manifest, load_user_vars(plugin_dir))}
    facts = jinni_client.variant_facts()
    _refuse_files_named_by_a_missing_setting(manifest, settings, facts)
    _settle_each_target(plugin_dir, manifest, settings, facts)


def settle_kept_originals_before_removal(plugin_dir: Path, manifest: dict,
                                         vars: dict[str, str]) -> None:
    """The same for a plugin about to be removed. A file named by a setting with no value is never
    put back by a removal, and its copy goes with the plugin, so it does not stop the others being
    settled. Raises when the printer's files cannot be read."""
    if not _holds_kept_copies(plugin_dir):
        return
    settings = {**vars, **with_declared_defaults(manifest, load_user_vars(plugin_dir))}
    _settle_each_target(plugin_dir, manifest, settings, jinni_client.variant_facts())


def _settle_each_target(plugin_dir: Path, manifest: dict, settings: dict[str, str],
                        facts: dict[str, str]) -> None:
    patched = fragments_by_target(plugin_dir, manifest, settings, facts)
    names = [Path(target).name for target in patched]
    shared_names = {name for name in names if names.count(name) > 1}
    for target, fragments in patched.items():
        _settle_one(plugin_dir, target, fragments, shared_names)


def _holds_kept_copies(plugin_dir: Path) -> bool:
    return any(path.is_file() for path in stock_copies(plugin_dir).rglob("*"))


def drop_kept_originals(plugin_dir: Path) -> None:
    """Drop every kept original of this plugin with its undo steps, so nothing writes them back."""
    shutil.rmtree(stock_copies(plugin_dir), ignore_errors=True)
    for target in written_files(plugin_dir):
        forget_written_file(plugin_dir, target)


def _refuse_files_named_by_a_missing_setting(manifest: dict, settings: dict[str, str],
                                             facts: dict[str, str]) -> None:
    """A patched file whose path is built from a setting that has no value cannot be found, so its
    copy cannot be checked. A reinstall would patch that copy, maybe an old firmware's file."""
    templates = [patch_def["file"]
                 for patch_def in normalize_install(manifest.get("install", {}), facts)["patches"]]
    missing = missing_required_vars(manifest, settings)
    naming = [name for name in missing if _names_setting(templates, settings, name)]
    if naming:
        raise ValueError(f"a patched file is named by a missing setting: {', '.join(naming)}")


def _names_setting(templates: list[str], settings: dict[str, str], setting_name: str) -> bool:
    """Whether the setting's value ends up in a path. Expanding with and without a value for it
    tells, where a plain text search would also match a longer setting's name it is the start of."""
    with_the_setting = {**settings, setting_name: _SETTING_PROBE}
    return any(expand(template, with_the_setting) != expand(template, settings)
               for template in templates)


def _settle_one(plugin_dir: Path, target: str, fragments: list[Path],
                shared_names: set[str]) -> None:
    orig_dir = stock_copies(plugin_dir)
    kept = kept_original(orig_dir, target)
    if not kept.is_file() or _kept_for_more_than_one_file(orig_dir, kept, shared_names):
        return
    kept_text = kept.read_text(errors="replace")
    current_original = _original_of_the_file_now(target, kept_text, fragments)
    if current_original is None:
        kept.unlink()
        forget_written_file(plugin_dir, str(Path(target)))
        return
    if unix_line_bytes(current_original) != unix_line_bytes(kept_text):
        kept.write_text(current_original)


def _kept_for_more_than_one_file(orig_dir: Path, kept: Path, shared_names: set[str]) -> bool:
    return kept.parent == orig_dir and kept.name in shared_names


def _original_of_the_file_now(target: str, kept_text: str, fragments: list[Path]) -> str | None:
    """The printer's file as it is now, with this plugin's patches taken off, or None when there is
    no file or the patches cannot be taken off it. A file equal to the kept copy already has them
    off (the plugin is switched off). Line endings never count as a difference."""
    live_text = jinni_client.fetch(target)
    if live_text is None:
        return None
    if unix_line_bytes(live_text) == unix_line_bytes(kept_text):
        return kept_text
    return without_patches(live_text, fragments)
