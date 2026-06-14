"""The deactivate/teardown lifecycle lives in core/packages/lifecycle.py: deactivate_all (the
reversible off-switch that keeps plugin files) and teardown (full uninstall + config-dir prune).
Both are vars-driven, deriving the plugin root from vars['BESPOK3D']."""

from pathlib import Path

from core.packages import lifecycle


def test_lifecycle_module_exposes_deactivate_all_and_teardown() -> None:
    assert callable(lifecycle.deactivate_all)
    assert callable(lifecycle.teardown)


def test_remove_include_line_drops_matching_lines_keeps_others(tmp_path: Path) -> None:
    cfg = tmp_path / "printer.cfg"
    cfg.write_text("[include bespok3d/klipper/main.cfg]\n[printer]\nfoo: 1\n")

    lifecycle._remove_include_line(cfg, "[include bespok3d/klipper")

    text = cfg.read_text()
    assert "bespok3d/klipper" not in text
    assert "[printer]" in text
    assert "foo: 1" in text


def test_remove_config_dir_preserves_user_files_but_takes_back_links(tmp_path: Path) -> None:
    klipper = tmp_path / "config" / "bespok3d" / "klipper"
    klipper.mkdir(parents=True)
    target = tmp_path / "userdata" / "spoolman.cfg"
    target.parent.mkdir(parents=True)
    target.write_text("generated")
    our_link = klipper / "spoolman.cfg"
    our_link.symlink_to(target)
    user_file = klipper / "my-overrides.cfg"
    user_file.write_text("user stuff")

    lifecycle._remove_bespok3d_config_dir({"BESPOK3D_KLIPPER": str(klipper)})

    assert not our_link.is_symlink()
    assert user_file.read_text() == "user stuff"
    assert (tmp_path / "config" / "bespok3d").is_dir()


def test_remove_config_dir_removes_dir_when_only_our_links(tmp_path: Path) -> None:
    klipper = tmp_path / "config" / "bespok3d" / "klipper"
    klipper.mkdir(parents=True)
    target = tmp_path / "userdata" / "rfid.cfg"
    target.parent.mkdir(parents=True)
    target.write_text("x")
    (klipper / "rfid.cfg").symlink_to(target)

    lifecycle._remove_bespok3d_config_dir({"BESPOK3D_KLIPPER": str(klipper)})

    assert not (tmp_path / "config" / "bespok3d").exists()
