# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which members of a .b3 archive the daemon is allowed to write, decided before it writes any.

Two independent refusals over the same member list:

Enumeration. The manifest signature vouches for a file by listing its sha256, so a member the
manifest never listed is unsigned payload that `verify_files` would never look at. An archive
carrying one is refused whole rather than partly trusted.

Containment. The daemon unpacks as root, and a member name is chosen by whoever built the package.
An absolute name discards the plugin directory entirely (`Path("/a/b") / "/etc/passwd"` is
`/etc/passwd`) and a `../` name stays textual in pathlib but is resolved by the kernel on the
`unlink` syscall, so either one points the pre-write delete at a path elsewhere on the printer.
"""

from pathlib import Path
from typing import TypeGuard

from .signatures import SIGNATURE_MEMBER

# manifest.json cannot carry its own hash and manifest.json.sig does not exist until after the
# manifest is final, so neither can ever appear in files[]. doc/ is listed by b3-builder but was
# left unlisted by the legacy shell packers, so packages already published carry it unlisted.
UNLISTED_BY_CONSTRUCTION = frozenset({"manifest.json", SIGNATURE_MEMBER})


def is_doc_member(name: str) -> bool:
    """Documentation ships inside the .b3 but is never deployed to the printer."""
    return name == "doc" or name.startswith("doc/")


def rendered_over(templates: list[dict]) -> frozenset[str]:
    """The plugin-dir paths install overwrites with a rendered template.

    A plugin may point a template at a path the package also ships, so the shipped copy is a
    placeholder that install replaces. The replacement's content comes from the `.tmpl` source,
    which carries its own checksum, so nothing is left unvouched by skipping the target.
    """
    return frozenset(str(template_def.get("to", "")) for template_def in templates)


def installed_files(manifest_files: list[dict], render_targets: frozenset[str]) -> list[dict]:
    """The manifest entries naming a file the printer still holds as the packer hashed it.

    Checksums answer "is what we wrote what the packer hashed", so an entry for something the daemon
    never writes, or writes with different content on purpose, has no comparable on-disk counterpart
    and would read as tampered. `unpack_package` drops the doc tree, and b3-builder lists it, so doc
    entries are one such case; a template's render target is the other, because install overwrites
    it and every later re-apply would hash the rendered file against the pre-render checksum.
    """
    return [entry for entry in manifest_files
            if not is_doc_member(str(entry.get("path", "")))
            and str(entry.get("path", "")) not in render_targets]


def stays_inside_its_parent_dir(chosen_name: object) -> TypeGuard[str]:
    """Whether a name the package chose is usable as one entry inside the directory it is joined to.

    Containment measures every member against the plugin directory, and that directory is named by
    the package itself, so an id of `../../etc/init.d` would relocate the whole extraction and leave
    each member "inside" the relocated root. A generated init script is the same story one level
    down: its file name also comes from the manifest, and the plugin's own `etc/init.d` is what it
    must stay inside. The name has to be one plain entry and no more, so an empty name (pathlib
    drops it on join, leaving the parent directory itself) is refused with the rest.
    """
    if not isinstance(chosen_name, str) or chosen_name in {".", ".."}:
        return False
    return Path(chosen_name).parts == (chosen_name,)


def undeclared_members(archive_members: list[str], manifest_files: object) -> list[str]:
    """The archive's members that the manifest never listed, and therefore never signed."""
    declared = _declared_paths(manifest_files)
    return sorted(name for name in archive_members if _needs_declaring(name, declared))


def escaping_members(plugin_dir: Path, archive_members: list[str]) -> list[str]:
    """The members whose destination lands outside the plugin's own directory."""
    return sorted(name for name in archive_members if not _stays_inside(plugin_dir, name))


def escaping_declared_paths(plugin_dir: Path, manifest_files: object) -> list[str]:
    """The manifest files[] paths that resolve outside the plugin's own directory. The manifest is
    package-chosen and drives a root chmod (apply_modes reads files[] directly), so a `..` or
    absolute path here aims that chmod at a file elsewhere on the printer even when every archive
    member stays contained. doc/ paths are measured too: apply_modes never drops them."""
    return sorted(
        path for path in _declared_paths(manifest_files) if not _stays_inside(plugin_dir, path)
    )


def _declared_paths(manifest_files: object) -> set[str]:
    """The paths a manifest declares. A malformed files[] declares nothing, so its members are
    refused as undeclared instead of crashing the install on an attacker-shaped manifest."""
    if not isinstance(manifest_files, list):
        return set()
    return {
        entry["path"] for entry in manifest_files
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    }


def _needs_declaring(name: str, declared: set[str]) -> bool:
    if name in declared or name in UNLISTED_BY_CONSTRUCTION or is_doc_member(name):
        return False
    # A zip may carry an entry for a directory itself; only the files inside it are payload.
    return not name.endswith("/")


def _stays_inside(plugin_dir: Path, name: str) -> bool:
    try:
        (plugin_dir / name).resolve().relative_to(plugin_dir.resolve())
    except (ValueError, OSError):
        return False
    return True
