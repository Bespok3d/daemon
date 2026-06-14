"""Deactivate and teardown: take Bespok3d off the printer, reversibly or completely.

deactivate_all stops every plugin and removes the include hooks but KEEPS the plugin files, writing
a marker so the next boot does not re-enable them (a reversible off-switch). teardown goes further:
it uninstalls every plugin and prunes the bespok3d config directory (keeping any user .cfg files),
the SSH caller then deletes the workspace. Both refuse mid-print and derive the plugin root from
vars['BESPOK3D'].
"""

from pathlib import Path

from .deactivation import neutralize_plugin
from .print_guard import guard_no_print
from .uninstaller import run_uninstall

_GLOBAL_DEACTIVATED_MARKER = "etc/deactivated"


def _remove_include_line(cfg_path: Path, pattern: str) -> None:
    if not cfg_path.exists():
        return
    text = cfg_path.read_text()
    cfg_path.write_text(
        "".join(line for line in text.splitlines(keepends=True) if pattern not in line)
    )


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
    guard_no_print("deactivate plugins")
    data_root = Path(vars["BESPOK3D"])
    _deactivate_plugins_in(data_root / "usr/local/plugins", vars)
    _remove_include_line(Path(vars["PRINTER_CFG"]), "[include bespok3d/klipper")
    _remove_include_line(Path(vars["MOONRAKER_CFG"]), "[include bespok3d/moonraker")
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


def _prune_links_and_empty_dirs(root: Path) -> None:
    """Remove our symlinks and any directories left empty, but keep real files.

    The `config/bespok3d` directory is intentionally preserved: a user may have dropped
    their own .cfg files in it. We only take back what Bespok3d put there (symlinks).
    """
    if not root.is_dir():
        return
    for child in sorted(root.iterdir()):
        if child.is_symlink():
            child.unlink()
        elif child.is_dir():
            _prune_links_and_empty_dirs(child)
    if not any(root.iterdir()):
        root.rmdir()


def _remove_bespok3d_config_dir(vars: dict[str, str]) -> None:
    config_dir = Path(vars.get("BESPOK3D_KLIPPER", "")).parent
    if config_dir.name == "bespok3d":
        _prune_links_and_empty_dirs(config_dir)


def teardown(vars: dict[str, str]) -> None:
    """Uninstall all plugins and remove config hooks; SSH caller removes the workspace."""
    # Guard at the top: the per-plugin uninstall guard is swallowed by _uninstall_plugins_in.
    guard_no_print("remove all plugins")
    data_root = Path(vars["BESPOK3D"])
    _uninstall_plugins_in(data_root / "usr/local/plugins", vars)
    _remove_include_line(Path(vars["PRINTER_CFG"]), "[include bespok3d/klipper")
    _remove_include_line(Path(vars["MOONRAKER_CFG"]), "[include bespok3d/moonraker")
    _remove_bespok3d_config_dir(vars)
