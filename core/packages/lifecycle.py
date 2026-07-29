# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deactivate and teardown: take Bespok3d off the printer, reversibly or completely.

deactivate_all stops every plugin and removes the include hooks but KEEPS the plugin files, writing
a marker so the next boot does not re-enable them (a reversible off-switch). teardown goes further:
it uninstalls every plugin and prunes the bespok3d config directory (keeping any user .cfg files),
the SSH caller then deletes the workspace. Both refuse mid-print and derive the plugin root from
vars['BESPOK3D']. Editing the printer's own config and pruning its include dirs is device-realm
mutation, so the daemon asks the jinni to do it (ADR-0037); the daemon owns only the $BESPOK3D tree
(the plugin dirs and the deactivated marker).
"""

from pathlib import Path

from .. import jinni_client
from ..safety import OperationContext, OperationKind
from .deactivation import neutralize_plugin
from .print_guard import guard_no_print
from .recovery import restart_services
from .uninstaller import remove_all_plugins

_GLOBAL_DEACTIVATED_MARKER = "etc/deactivated"


def _deactivate_plugin_dir(plugin_dir: Path, vars: dict[str, str]) -> None:
    if not plugin_dir.is_dir() or not (plugin_dir / "manifest.json").exists():
        return
    neutralize_plugin(plugin_dir, vars)


def _deactivate_plugins_in(plugin_root: Path, vars: dict[str, str]) -> None:
    if not plugin_root.exists():
        return
    for plugin_dir in plugin_root.iterdir():
        _deactivate_plugin_dir(plugin_dir, vars)


def _write_deactivated_marker(data_root: Path) -> None:
    marker = data_root / _GLOBAL_DEACTIVATED_MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()


def deactivate_all(vars: dict[str, str]) -> None:
    """Stop all plugins and remove config hooks; leave plugin files intact."""
    guard_no_print()
    data_root = Path(vars["BESPOK3D"])
    _deactivate_plugins_in(data_root / "usr/local/plugins", vars)
    jinni_client.remove_bespok3d_includes()
    _write_deactivated_marker(data_root)


def teardown(vars: dict[str, str]) -> None:
    """Uninstall all plugins and remove config hooks; SSH caller removes the workspace. Remove every
    plugin's effect and files first, drop the include hooks, THEN restart the core services once, so
    a full teardown bounces Klipper/Moonraker a single time into the final clean state rather than
    once per plugin (the restart storm)."""
    # Guard at the top: remove_all_plugins removes unconditionally, with no per-plugin guard.
    guard_no_print()
    data_root = Path(vars["BESPOK3D"])
    plugin_root = data_root / "usr/local/plugins"
    restart_commands = remove_all_plugins(plugin_root, vars)
    jinni_client.remove_bespok3d_includes()
    if restart_commands:
        context = OperationContext(OperationKind.TEARDOWN)
        restart_services(plugin_root, restart_commands, vars, context)
    jinni_client.prune_bespok3d_config_dir()
