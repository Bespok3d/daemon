"""Taking a plugin out of effect and recording it: run its stop commands, undo what install placed
on the system (symlinks, patched files, linked libs, venv), and write/clear the deactivated and
recovery-failure markers. Shared by the recovery safety net and the uninstall/teardown paths.
"""

import json
from pathlib import Path

from .. import jinni_client
from ..intent import normalize_install
from .manifest import manifest_at
from .patches import restore_original_files
from .placement import remove_plugin_symlinks
from .python_deps import remove_plugin_site_links, remove_plugin_venv
from .user_vars import expand, load_user_vars

DEACTIVATED_MARKER = "deactivated.json"
RECOVERY_FAILURE_MARKER = "recovery_failure.json"


def run_stop_commands(cmds: list[str], vars: dict[str, str]) -> None:
    """Run a plugin's stop commands best-effort; the jinni executes them (ADR-0037), the daemon only
    resolves and forwards. The outcome is ignored: a stop that fails (service already down) must not
    block taking the plugin off the system."""
    expanded = [expand(cmd, vars) for cmd in cmds]
    if expanded:
        jinni_client.run_actions(expanded)


def clear_failure_markers(plugin_dir: Path) -> None:
    """A plugin that re-applies cleanly is no longer failed or deactivated; drop stale markers."""
    (plugin_dir / DEACTIVATED_MARKER).unlink(missing_ok=True)
    (plugin_dir / RECOVERY_FAILURE_MARKER).unlink(missing_ok=True)


def neutralize_plugin(plugin_dir: Path, vars: dict[str, str]) -> None:
    """Stop a plugin affecting the system: drop its symlinks, restore patched files, remove its
    linked libs and venv. Files in the plugin dir stay, so recover/reactivate can rebuild it."""
    manifest = manifest_at(plugin_dir)
    full_vars = {**vars, **load_user_vars(plugin_dir)}
    ops = normalize_install(manifest.get("install", {}))
    run_stop_commands(ops["stops"] + manifest.get("stop", []), full_vars)
    remove_plugin_symlinks(ops["symlinks"], plugin_dir, full_vars)
    restore_original_files(ops["patches"], plugin_dir / "patches_orig", full_vars)
    remove_plugin_site_links(plugin_dir, full_vars)
    remove_plugin_venv(plugin_dir.name, full_vars)


def deactivate_plugin(plugin_dir: Path, vars: dict[str, str], reason: str) -> None:
    if (plugin_dir / "manifest.json").exists():
        neutralize_plugin(plugin_dir, vars)
    (plugin_dir / DEACTIVATED_MARKER).write_text(json.dumps({"reason": reason}))
