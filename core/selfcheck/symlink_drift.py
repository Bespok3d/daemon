# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-plugin drift: the links one plugin's manifest says should exist, against the filesystem.

Covers both the symlinks the manifest declares outright and the autostart links the daemon derives
from the manifest's services and kernel modules: a plugin whose boot script is no longer wired into
the autostart dir is installed but dead at the next boot, which reads to the user exactly like a
missing symlink. Read-only; never mutates.
"""
import json
import os
from pathlib import Path
from typing import Any

from ..autostart import autostart_additions, kmodule_ops, service_ops
from ..packages.user_vars import expand, load_user_vars

ISSUE_MISSING = "missing"
ISSUE_NOT_A_SYMLINK = "not_a_symlink"
ISSUE_WRONG_TARGET = "wrong_target"
ISSUE_DANGLING_TARGET = "dangling_target"


def _expected_link_endpoints(
    plugin_dir: Path, link: dict[str, str], vars: dict[str, str]
) -> tuple[Path, Path]:
    expected_target = (plugin_dir / link["from"]).resolve()
    link_path = Path(expand(link["to"], vars))
    return expected_target, link_path


def _wrong_thing_at_the_link_path(link_path: Path, expected_target: Path) -> dict[str, str] | None:
    """What is wrong with the link itself: nothing there at all, or a real file sitting where the
    plugin's symlink belongs."""
    if link_path.is_symlink():
        return None
    if link_path.exists():
        return {"kind": ISSUE_NOT_A_SYMLINK, "link_path": str(link_path)}
    return {"kind": ISSUE_MISSING, "link_path": str(link_path),
            "expected_target": str(expected_target)}


def _wrong_thing_at_the_other_end(link_path: Path, expected_target: Path) -> dict[str, str] | None:
    """What the symlink points at: someone else's file, or nothing at all."""
    actual_target = os.readlink(link_path)
    if Path(actual_target) != expected_target:
        return {"kind": ISSUE_WRONG_TARGET, "link_path": str(link_path),
                "expected_target": str(expected_target), "actual_target": actual_target}
    if link_path.exists():
        return None
    return {"kind": ISSUE_DANGLING_TARGET, "link_path": str(link_path),
            "expected_target": str(expected_target)}


def _classify_symlink(
    plugin_dir: Path, link: dict[str, str], vars: dict[str, str]
) -> dict[str, str] | None:
    expected_target, link_path = _expected_link_endpoints(plugin_dir, link, vars)
    at_the_link = _wrong_thing_at_the_link_path(link_path, expected_target)
    if at_the_link is not None:
        return at_the_link
    return _wrong_thing_at_the_other_end(link_path, expected_target)


def _autostart_links(install: dict[str, Any]) -> list[dict[str, str]]:
    service_links, _, _ = autostart_additions(install.get("service", []), service_ops)
    kmodule_links, _, _ = autostart_additions(install.get("kmodule", []), kmodule_ops)
    return service_links + kmodule_links


def expected_links(manifest: dict[str, Any]) -> list[dict[str, str]]:
    install = manifest.get("install", {})
    return list(install.get("symlinks", [])) + _autostart_links(install)


def _declared_manifest(manifest_path: Path) -> dict[str, Any] | None:
    """What the plugin says its links are, or None when it says nothing readable.

    Drift is checked for every plugin on the printer in one sweep, so a single plugin whose manifest
    was truncated (a power cut mid install is how that happens on a printer) must cost that plugin's
    row and never the whole printer's drift report. Whether a corrupt manifest is repairable is the
    install-time integrity check's question, not this read-only sweep's."""
    if not manifest_path.exists():
        return None
    try:
        return dict(json.loads(manifest_path.read_text()))
    except (ValueError, UnicodeDecodeError, OSError, TypeError):
        return None


def plugin_drift(plugin_dir: Path, vars: dict[str, str]) -> dict[str, Any] | None:
    """One plugin's link issues, or None when every link it declares is in place."""
    manifest_path = plugin_dir / "manifest.json"
    manifest = _declared_manifest(manifest_path)
    if manifest is None:
        return None
    full_vars = {**vars, **load_user_vars(plugin_dir)}
    classified = [_classify_symlink(plugin_dir, link, full_vars)
                  for link in expected_links(manifest)]
    symlink_issues = [issue for issue in classified if issue is not None]
    if not symlink_issues:
        return None
    return {"plugin_id": plugin_dir.name, "symlink_issues": symlink_issues}
