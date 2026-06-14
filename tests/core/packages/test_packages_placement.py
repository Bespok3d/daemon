"""Placement (the symlink/dir/mode family) has a canonical home in core.packages.placement and stays
reachable from the core.packages namespace, where the orchestrator drives it. These guard the
stock-original backup/restore contract that lets teardown put the firmware back."""
from pathlib import Path

from core import packages
from core.packages import placement


def test_symbols_reexported_from_package_namespace() -> None:
    assert packages._create_symlinks is placement._create_symlinks
    assert packages._create_dirs is placement._create_dirs
    assert packages._apply_modes is placement._apply_modes
    assert packages._remove_plugin_symlinks is placement._remove_plugin_symlinks


def test_create_dirs_expands_vars(tmp_path: Path) -> None:
    phase = placement._create_dirs(["$ROOT/data"], {"ROOT": str(tmp_path)})
    assert (tmp_path / "data").is_dir()
    assert all(item["ok"] for item in phase["items"])


def test_apply_modes_sets_file_mode(tmp_path: Path) -> None:
    (tmp_path / "run.sh").write_text("echo hi\n")
    placement._apply_modes(tmp_path, [{"path": "run.sh", "mode": "755"}])
    assert (tmp_path / "run.sh").stat().st_mode & 0o777 == 0o755


def test_symlink_install_backs_up_stock_original_and_restore_returns_it(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugin"
    (plugin_dir / "files").mkdir(parents=True)
    (plugin_dir / "files" / "new.cfg").write_text("plugin version\n")
    destination = tmp_path / "etc" / "thing.cfg"
    destination.parent.mkdir()
    destination.write_text("stock version\n")
    link = {"from": "files/new.cfg", "to": str(destination)}

    placement._create_symlinks([link], plugin_dir, {})
    assert destination.is_symlink()
    backup = placement._symlink_backup_path(plugin_dir, destination)
    assert backup.read_text() == "stock version\n"

    placement._remove_plugin_symlinks([link], plugin_dir, {})
    assert not destination.is_symlink()
    assert destination.read_text() == "stock version\n"


def test_replacing_a_symlink_does_not_capture_it_as_a_backup(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    destination = tmp_path / "link"
    destination.symlink_to(tmp_path / "elsewhere")
    backup = placement._symlink_backup_path(plugin_dir, destination)

    placement._replace_with_symlink(tmp_path / "source", destination, backup)
    assert not backup.exists()
