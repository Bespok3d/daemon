"""Placement (the symlink/dir/mode family) has a canonical home in core.packages.placement. These
guard the stock-original backup/restore contract that lets teardown put the firmware back."""
from pathlib import Path

from core.packages import placement


def test_create_dirs_expands_vars(tmp_path: Path) -> None:
    phase = placement.create_dirs(["$ROOT/data"], {"ROOT": str(tmp_path)})
    assert (tmp_path / "data").is_dir()
    assert all(item["ok"] for item in phase["items"])


def test_apply_modes_sets_file_mode(tmp_path: Path) -> None:
    (tmp_path / "run.sh").write_text("echo hi\n")
    placement.apply_modes(tmp_path, [{"path": "run.sh", "mode": "755"}])
    assert (tmp_path / "run.sh").stat().st_mode & 0o777 == 0o755


def test_symlink_install_backs_up_stock_original_and_restore_returns_it(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugin"
    (plugin_dir / "files").mkdir(parents=True)
    (plugin_dir / "files" / "new.cfg").write_text("plugin version\n")
    destination = tmp_path / "etc" / "thing.cfg"
    destination.parent.mkdir()
    destination.write_text("stock version\n")
    link = {"from": "files/new.cfg", "to": str(destination)}

    placement.create_symlinks([link], plugin_dir, {})
    assert destination.is_symlink()
    backup = placement._symlink_backup_path(plugin_dir, destination)
    assert backup.read_text() == "stock version\n"

    placement.remove_plugin_symlinks([link], plugin_dir, {})
    assert not destination.is_symlink()
    assert destination.read_text() == "stock version\n"


def test_replacing_a_symlink_does_not_capture_it_as_a_backup(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    destination = tmp_path / "link"
    destination.symlink_to(tmp_path / "elsewhere")
    backup = placement._symlink_backup_path(plugin_dir, destination)

    placement.replace_with_symlink(tmp_path / "source", destination, backup)
    assert not backup.exists()


def test_points_into_true_when_symlink_resolves_into_target(tmp_path: Path) -> None:
    baked = tmp_path / "baked"
    baked.mkdir()
    (baked / "humanize").write_text("")
    link = tmp_path / "humanize"
    link.symlink_to(baked / "humanize")
    assert placement.points_into(link, baked)


def test_points_into_false_for_symlink_outside_target(tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    (other / "humanize").write_text("")
    link = tmp_path / "humanize"
    link.symlink_to(other / "humanize")
    assert not placement.points_into(link, tmp_path / "baked")


def test_symlink_owner_is_first_path_component_under_root(tmp_path: Path) -> None:
    owner = tmp_path / "plugins" / "notifier" / "files" / "site-packages" / "humanize"
    owner.mkdir(parents=True)
    link = tmp_path / "humanize"
    link.symlink_to(owner)
    assert placement.symlink_owner(link, tmp_path / "plugins") == "notifier"


def test_symlink_owner_none_for_real_file_or_link_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    root.mkdir()
    real = tmp_path / "real"
    real.write_text("")
    assert placement.symlink_owner(real, root) is None
    outside = tmp_path / "outside"
    outside.write_text("")
    link = tmp_path / "link"
    link.symlink_to(outside)
    assert placement.symlink_owner(link, root) is None
