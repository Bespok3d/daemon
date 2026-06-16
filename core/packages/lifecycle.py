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
from .deactivation import neutralize_plugin
from .print_guard import guard_no_print
from .uninstaller import run_uninstall

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


def _uninstall_plugins_in(plugin_root: Path, vars: dict[str, str]) -> None:
    if not plugin_root.exists():
        return
    plugin_ids = [plugin_dir.name for plugin_dir in plugin_root.iterdir() if plugin_dir.is_dir()]
    for plugin_id in plugin_ids:
        try:
            run_uninstall(plugin_root, plugin_id, vars)
        except Exception:  # noqa: BLE001  teardown is best-effort: keep removing the rest
            pass


def teardown(vars: dict[str, str]) -> None:
    """Uninstall all plugins and remove config hooks; SSH caller removes the workspace."""
    # Guard at the top: the per-plugin uninstall guard is swallowed by _uninstall_plugins_in.
    guard_no_print()
    data_root = Path(vars["BESPOK3D"])
    _uninstall_plugins_in(data_root / "usr/local/plugins", vars)
    jinni_client.remove_bespok3d_includes()
    jinni_client.prune_bespok3d_config_dir()
