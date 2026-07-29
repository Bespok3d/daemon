# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Placement in core.packages.placement: directories, file modes, and resolving the symlink family
for the jinni to wire. The symlink IO and the stock-original backup/restore contract moved to the
jinni's wiring facet (ADR-0037); these cover what the daemon still owns: dir/mode creation, the
read-side ownership helpers, and that create_symlinks/remove delegate to the jinni's wire/unwire."""
from pathlib import Path

from core.packages import placement
from tests.fakes import FakeKlipperJinni


def test_create_dirs_expands_vars(tmp_path: Path) -> None:
    phase = placement.create_dirs(["$ROOT/data"], {"ROOT": str(tmp_path)})
    assert (tmp_path / "data").is_dir()
    assert all(item["ok"] for item in phase["items"])


def test_apply_modes_sets_file_mode(tmp_path: Path) -> None:
    (tmp_path / "run.sh").write_text("echo hi\n")
    placement.apply_modes(tmp_path, [{"path": "run.sh", "mode": "755"}])
    assert (tmp_path / "run.sh").stat().st_mode & 0o777 == 0o755


def test_create_symlinks_resolves_and_wires_through_the_jinni(
    tmp_path: Path, device_jinni: FakeKlipperJinni,
) -> None:
    """The daemon resolves the (source, destination) and asks the jinni to wire it; the symlink
    appears at the resolved destination."""
    plugin_dir = tmp_path / "plugin"
    (plugin_dir / "files").mkdir(parents=True)
    (plugin_dir / "files" / "new.cfg").write_text("plugin version\n")
    destination = tmp_path / "etc" / "thing.cfg"
    link = {"from": "files/new.cfg", "to": str(destination)}

    phase = placement.create_symlinks([link], plugin_dir, {})

    assert all(item["ok"] for item in phase["items"])
    assert destination.is_symlink()
    assert destination.read_text() == "plugin version\n"

    placement.remove_plugin_symlinks([link], plugin_dir, {})
    assert not destination.exists()


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
