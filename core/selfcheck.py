# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Self-check: diff the expected on-printer state (each plugin's manifest plus persisted
user_vars) against the actual filesystem. Read-only; never mutates.

Scope (v1): symlink drift only. Patches and templates are harder to verify cheaply.
"""

import json
import os
from pathlib import Path
from typing import Any

from . import packages
from .packages.user_vars import expand, load_user_vars

_DEACTIVATED_MARKER = "deactivated.json"

ISSUE_MISSING = "missing"
ISSUE_NOT_A_SYMLINK = "not_a_symlink"
ISSUE_WRONG_TARGET = "wrong_target"


def _expected_link_endpoints(
    plugin_dir: Path, link: dict, vars: dict[str, str]
) -> tuple[Path, Path]:
    expected_target = (plugin_dir / link["from"]).resolve()
    link_path = Path(expand(link["to"], vars))
    return expected_target, link_path


def _classify_symlink(
    plugin_dir: Path, link: dict, vars: dict[str, str]
) -> dict[str, str] | None:
    expected_target, link_path = _expected_link_endpoints(plugin_dir, link, vars)
    if not link_path.exists() and not link_path.is_symlink():
        return {
            "kind": ISSUE_MISSING,
            "link_path": str(link_path),
            "expected_target": str(expected_target),
        }
    if not link_path.is_symlink():
        return {"kind": ISSUE_NOT_A_SYMLINK, "link_path": str(link_path)}
    actual_target = os.readlink(link_path)
    if Path(actual_target) != expected_target:
        return {
            "kind": ISSUE_WRONG_TARGET,
            "link_path": str(link_path),
            "expected_target": str(expected_target),
            "actual_target": actual_target,
        }
    return None


def _plugin_drift(plugin_dir: Path, vars: dict[str, str]) -> dict[str, Any] | None:
    manifest_path = plugin_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    manifest = json.loads(manifest_path.read_text())
    full_vars = {**vars, **load_user_vars(plugin_dir)}
    declared_links = manifest.get("install", {}).get("symlinks", [])
    classified = [_classify_symlink(plugin_dir, link, full_vars) for link in declared_links]
    symlink_issues = [issue for issue in classified if issue is not None]
    if not symlink_issues:
        return None
    return {"plugin_id": plugin_dir.name, "symlink_issues": symlink_issues}


def _active_plugin_dirs() -> list[Path]:
    plugin_root = packages.PLUGIN_ROOT
    if not plugin_root.exists():
        return []
    return [
        plugin_dir
        for plugin_dir in plugin_root.iterdir()
        if plugin_dir.is_dir() and not (plugin_dir / _DEACTIVATED_MARKER).exists()
    ]


def run_selfcheck(vars: dict[str, str]) -> list[dict[str, Any]]:
    """Return a per-plugin list of drift reports; empty list means no drift detected."""
    drift_reports = [_plugin_drift(plugin_dir, vars) for plugin_dir in _active_plugin_dirs()]
    return [report for report in drift_reports if report is not None]
