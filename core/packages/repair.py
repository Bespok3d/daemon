# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Put the printer itself right, before any plugin is re-applied.

The counterpart of `core.selfcheck.printer_state`: everything that check can report about the
printer (rather than about one plugin) is something this module fixes, so a user who is shown a
problem is shown a button that actually clears it. It runs first in `recover`, because a plugin
re-applied into a printer whose config no longer includes us is still a plugin the printer ignores.

Idempotent by construction: every step asks for the end state, not for a change, so running it on a
sound printer does nothing and running it twice is the same as running it once. What the end state
IS follows the user's last intent: the global deactivated marker means the wiring belongs off.
"""
import shutil
from pathlib import Path

from .. import jinni_client
from ..data_root import REQUIRED_DIRECTORIES
from .deactivation import RECOVERY_FAILURE_MARKER
from .lifecycle import GLOBAL_DEACTIVATED_MARKER
from .plugin_venv import remove_plugin_venv
from .python_deps import remove_plugin_site_links


def _rewire_printer_config(switched_off: bool) -> None:
    """Both directions, because both are reportable. A printer the user switched back on needs its
    include lines returned; one left switched off with the lines still in place loads plugins the
    user asked to be gone."""
    if switched_off:
        jinni_client.remove_bespok3d_includes()
        return
    jinni_client.restore_bespok3d_includes()


def _create_required_directories(data_root: Path) -> None:
    for relative in REQUIRED_DIRECTORIES:
        (data_root / relative).mkdir(parents=True, exist_ok=True)


def _finish_removing(plugin_dir: Path, vars: dict[str, str]) -> None:
    """A plugin dir with no manifest is the wreckage of an uninstall that stopped partway: nothing
    can read it, install it or remove it by name again. Finish the removal its own uninstall would
    have done, so the next install of that plugin starts from clean ground."""
    remove_plugin_site_links(plugin_dir, vars)
    remove_plugin_venv(plugin_dir.name, vars)
    shutil.rmtree(plugin_dir, ignore_errors=True)


def _sweep_half_removed_plugins(plugin_root: Path, vars: dict[str, str]) -> None:
    if not plugin_root.is_dir():
        return
    for plugin_dir in sorted(plugin_root.iterdir()):
        if plugin_dir.is_dir() and not (plugin_dir / "manifest.json").exists():
            _finish_removing(plugin_dir, vars)


def _clear_failure_markers(plugin_root: Path) -> None:
    """Drop the evidence marker of a run that never finished, so the plugin is re-applied on this
    pass instead of being skipped forever. A plugin that fails again is deactivated by the safety
    net, which is a state the user can see and act on rather than a printer left broken."""
    if not plugin_root.is_dir():
        return
    for plugin_dir in sorted(plugin_root.iterdir()):
        (plugin_dir / RECOVERY_FAILURE_MARKER).unlink(missing_ok=True)


def restore_printer_state(data_root: Path, plugin_root: Path, vars: dict[str, str]) -> None:
    """Make the printer sound again: wired as the user asked, tree whole, no wreckage left over."""
    _create_required_directories(data_root)
    _rewire_printer_config((data_root / GLOBAL_DEACTIVATED_MARKER).exists())
    _sweep_half_removed_plugins(plugin_root, vars)
    _clear_failure_markers(plugin_root)
    jinni_client.prune_dead_config_links()
