# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Plugin Python deps (ADR-0036): provision a per-plugin venv or symlink baked packages into the
system site-packages, then tear them down. CI bakes the deps into the .b3, so no pip runs on the
printer.

This module owns the dep POLICY and the system site-packages side of the IO: which file a plugin
declared, version coexistence across plugins that share the system interpreter, and the symlink
actions. The per-plugin venv side lives in core/packages/plugin_venv.py; the pure path/name builders
in core/python_env.py; the generic symlink mechanics (placing a link, finding its owner, testing
where it points) in core/packages/placement.py.

A plugin declares its deps as a plain file, never a manifest field, and the two are mutually
exclusive: requirements.txt -> a per-plugin venv for the plugin's own service;
klipper_requirements.txt -> baked packages symlinked into the system site-packages so Klipper or
Moonraker can import them.
"""

import subprocess
from pathlib import Path

from protocol import ActionResult

from .. import jinni_client, python_env
from ..results import item, phase
from .baked_deps import baked_top_level_names
from .placement import points_into, symlink_owner
from .plugin_venv import provision_venv_phase


def _already_importable(module: str) -> bool:
    """True if the base interpreter already provides the module: never shadow a system package."""
    probe = f"import importlib.util,sys; sys.exit(0 if importlib.util.find_spec({module!r}) else 1)"
    result = subprocess.run(["python3", "-c", probe], capture_output=True, check=False)
    return result.returncode == 0


def _baked_version(baked: Path, name: str) -> str:
    module = python_env.import_name(name).lower()
    if not baked.is_dir():
        return ""
    for info in baked.iterdir():
        if info.name.endswith(".dist-info") and info.name.lower().startswith(module + "-"):
            return info.name[len(module) + 1:-len(".dist-info")]
    return ""


def _link_conflict(plugin_root: Path, label: str, owner: str, plugin_dir: Path, name: str) -> dict:
    ours = _baked_version(python_env.baked_site_packages_dir(plugin_dir), name)
    theirs = _baked_version(python_env.baked_site_packages_dir(plugin_root / owner), name)
    if ours and theirs and ours == theirs:
        return item(f"{label}: already provided by {owner} at {ours}", ok=True)
    return item(
        f"{label}: refused, {owner} already provides {name} at a different version "
        f"({theirs or 'unknown'} vs {ours or 'unknown'}); one interpreter holds one version",
        ok=False,
    )


def _site_link_precheck(plugin_root: Path, plugin_dir: Path, site_pkgs: Path, name: str) -> dict | None:  # noqa: E501
    """A terminal item if we must not link (a satisfied no-op or a refusal), else None to link."""
    module = python_env.import_name(name)
    if _already_importable(module):
        return item(f"{name}: already provided by the system Python, not re-linked", ok=True)
    owner = symlink_owner(site_pkgs / name, plugin_root)
    if owner is not None and owner != plugin_dir.name:
        return _link_conflict(plugin_root, f"link {name}", owner, plugin_dir, name)
    destination = site_pkgs / name
    if destination.exists() and not destination.is_symlink():
        return item(f"link {name}: refused, a real file already occupies {destination}", ok=False)
    return None


def _link_result_item(name: str, result: ActionResult) -> dict:
    return item(f"link {name}", ok=result.ok, output=result.output)


def _link_site_packages(plugin_root: Path, plugin_dir: Path, vars: dict[str, str]) -> dict | None:
    """Symlink baked packages into the system site-packages for a Klipper/Moonraker extra. None if
    absent. The precheck (already-importable, cross-plugin version coexistence, real-file-in-the-
    way) is a read the daemon owns; the symlink IO is the jinni's wire actuation (ADR-0037)."""
    if not (plugin_dir / python_env.KLIPPER_REQUIREMENTS_FILE).is_file():
        return None
    site_pkgs = python_env.system_site_packages(vars)
    if site_pkgs is None:
        return phase("site_packages", "System Python links", [item("no system site-packages on this host; skipped", ok=True)])  # noqa: E501
    site_pkgs.mkdir(parents=True, exist_ok=True)
    baked = python_env.baked_site_packages_dir(plugin_dir)
    prechecks = [(name, _site_link_precheck(plugin_root, plugin_dir, site_pkgs, name)) for name in baked_top_level_names(plugin_dir)]  # noqa: E501
    to_link = [name for name, terminal in prechecks if terminal is None]
    requests = [{"source": str(baked / name), "destination": str(site_pkgs / name)} for name in to_link]  # noqa: E501
    results = dict(zip(to_link, jinni_client.wire(str(plugin_dir), requests)))
    items = [terminal if terminal is not None else _link_result_item(name, results[name]) for name, terminal in prechecks]  # noqa: E501
    return phase("site_packages", "System Python links", items)


def provision_deps_phases(plugin_root: Path, plugin_dir: Path, vars: dict[str, str]) -> list[dict]:
    """The venv phase and the site-packages-link phase, whichever applies (mutually exclusive)."""
    return [dep_phase for dep_phase in (provision_venv_phase(plugin_dir, vars), _link_site_packages(plugin_root, plugin_dir, vars)) if dep_phase is not None]  # noqa: E501


def remove_plugin_site_links(plugin_dir: Path, vars: dict[str, str]) -> list[str]:
    """Remove the system site-packages symlinks that point into this plugin's baked deps. The daemon
    finds them (a read over its baked tree); the jinni unwires them (the device-realm unlink)."""
    site_pkgs = python_env.system_site_packages(vars)
    if site_pkgs is None or not site_pkgs.is_dir():
        return []
    baked = python_env.baked_site_packages_dir(plugin_dir)
    destinations = [entry for entry in sorted(site_pkgs.iterdir())
                    if entry.is_symlink() and points_into(entry, baked)]
    if destinations:
        jinni_client.unwire(str(plugin_dir), [str(entry) for entry in destinations])
    return [entry.name for entry in destinations]
