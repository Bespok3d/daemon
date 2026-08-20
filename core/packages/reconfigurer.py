# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Config-only reconfigure: re-render an installed plugin's config templates from new user values
and restart its services, without re-applying files, symlinks, or patches.

Lighter than a reinstall (it relies on installs being idempotent), and split from the fresh-install
spine in `installer.py` so each op file stays one responsibility.
"""

from pathlib import Path

from .. import jinni_client
from ..intent import normalize_install
from ..safety import OperationKind
from .archive import fix_ownership
from .manifest import manifest_at
from .plugin_dir import contained_plugin_dir
from .print_guard import guard_no_print_during_restart
from .recovery import op_context, restart_phases
from .start_commands import run_plugin_start_commands
from .templates import render_templates
from .user_vars import (
    persist_user_vars,
    refuse_missing_settings,
    with_declared_defaults,
    with_plugin_venv,
)


def run_reconfigure(
    plugin_root: Path,
    plugin_id: str,
    vars: dict[str, str],
    user_vars: dict[str, str],
) -> tuple[str, list[dict]]:
    """Re-render a plugin's config templates from new values and restart its services.

    Lighter than a reinstall: files, symlinks, and patches are left untouched; only the
    rendered config files change. Relies on installs being idempotent.
    """
    plugin_dir = contained_plugin_dir(plugin_root, plugin_id)
    if not (plugin_dir / "manifest.json").exists():
        raise ValueError(f"plugin {plugin_id!r} is not installed")
    manifest = manifest_at(plugin_dir)
    guard_no_print_during_restart(manifest)

    settings = with_declared_defaults(manifest, user_vars)
    full_vars = with_plugin_venv({**vars, **settings}, plugin_id)
    refuse_missing_settings(manifest, full_vars)
    inst = normalize_install(manifest.get("install", {}), jinni_client.variant_facts())
    persist_user_vars(plugin_dir, settings)
    start_phase, deferred = run_plugin_start_commands(inst.get("start", []), full_vars)
    ctx = op_context(OperationKind.RECONFIGURE, manifest)
    phases = [
        render_templates(inst.get("templates", []), plugin_dir, full_vars),
        fix_ownership(plugin_dir, full_vars.get("RUNTIME_USER", "")),
        start_phase,
    ]
    phases.extend(restart_phases(plugin_root, deferred, full_vars, ctx))
    return plugin_id, phases
