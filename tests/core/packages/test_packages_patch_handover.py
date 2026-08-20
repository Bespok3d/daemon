# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Handing a patched file over to a new owner: the new owner must end up holding the file's true
original, never another plugin's patched output, and the old owners must stop holding a copy of it.

The fixture printer is fake throughout: a made-up panel file patched by a made-up plugin."""
from pathlib import Path

import pytest

from core import jinni_client
from tests.core.packages.fake_panel_printer import (
    BASE_LAYER,
    COLS_FRAGMENT,
    PANEL,
    PANEL_TWEAKS,
    STOCK_PANEL,
    TWEAKED_PANEL,
    hand_over,
    install_panel_patcher,
    kept_panel,
)


@pytest.fixture(autouse=True)
def live_panel(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """The printer's live files, patched by whoever owns them; the panel carries panel-tweaks'
    change by default, which is exactly what the new owner must not mistake for the original."""
    device_files = {PANEL: TWEAKED_PANEL}
    monkeypatch.setattr(jinni_client, "variant_facts", dict)
    monkeypatch.setattr(jinni_client, "fetch", device_files.get)
    return device_files



def test_the_new_owner_adopts_the_original_the_old_owner_kept(tmp_path: Path) -> None:
    old_owner = install_panel_patcher(tmp_path, PANEL_TWEAKS, kept_copy=STOCK_PANEL)
    adopter = install_panel_patcher(tmp_path, BASE_LAYER, None, COLS_FRAGMENT)
    result = hand_over(tmp_path, adopter)
    assert result["ok"] is True
    assert PANEL_TWEAKS in result["label"]
    assert (kept_panel(adopter)).read_text() == STOCK_PANEL
    assert not (kept_panel(old_owner)).exists()


def test_the_other_plugins_change_is_taken_off_the_live_file_not_adopted_with_it(
    tmp_path: Path,
) -> None:
    """The new owner patches the file its own way, so it cannot recognise the other plugin's change
    in what the printer holds. Capturing the live file would bake that change in forever."""
    install_panel_patcher(tmp_path, PANEL_TWEAKS, kept_copy=None)
    adopter = install_panel_patcher(tmp_path, BASE_LAYER, None, COLS_FRAGMENT)
    assert hand_over(tmp_path, adopter)["ok"] is True
    assert (kept_panel(adopter)).read_text() == STOCK_PANEL


def test_a_kept_copy_that_already_carries_the_patch_is_not_taken_for_the_original(
    tmp_path: Path,
) -> None:
    install_panel_patcher(tmp_path, PANEL_TWEAKS, kept_copy=TWEAKED_PANEL)
    adopter = install_panel_patcher(tmp_path, BASE_LAYER, None, COLS_FRAGMENT)
    assert hand_over(tmp_path, adopter)["ok"] is True
    assert (kept_panel(adopter)).read_text() == STOCK_PANEL


def test_nothing_is_taken_over_when_no_original_can_be_proven(
    tmp_path: Path, live_panel: dict[str, str],
) -> None:
    live_panel[PANEL] = "panel start\nrows: written by hand\ncols: 2\npanel end\n"
    old_owner = install_panel_patcher(tmp_path, PANEL_TWEAKS, kept_copy=TWEAKED_PANEL)
    adopter = install_panel_patcher(tmp_path, BASE_LAYER, None, COLS_FRAGMENT)
    result = hand_over(tmp_path, adopter)
    assert result["ok"] is False
    assert not (kept_panel(adopter)).exists()
    assert (kept_panel(old_owner)).read_text() == TWEAKED_PANEL


def test_a_file_no_installed_plugin_patches_is_adopted_from_the_printer(
    tmp_path: Path, live_panel: dict[str, str],
) -> None:
    live_panel[PANEL] = STOCK_PANEL
    adopter = install_panel_patcher(tmp_path, BASE_LAYER, None, COLS_FRAGMENT)
    result = hand_over(tmp_path, adopter)
    assert result["ok"] is True
    assert (kept_panel(adopter)).read_text() == STOCK_PANEL


def test_a_missing_live_file_is_reported_not_adopted(
    tmp_path: Path, live_panel: dict[str, str],
) -> None:
    live_panel.clear()
    adopter = install_panel_patcher(tmp_path, BASE_LAYER, None, COLS_FRAGMENT)
    assert hand_over(tmp_path, adopter)["ok"] is False


def _every_file_under(plugin_root: Path) -> list[tuple[Path, bytes]]:
    """Every file the printer holds under the plugin root, with its bytes, so a second run can be
    shown to have changed nothing at all."""
    return sorted((path, path.read_bytes()) for path in plugin_root.rglob("*") if path.is_file())


def test_handing_the_same_file_over_twice_changes_nothing(tmp_path: Path) -> None:
    old_owner = install_panel_patcher(tmp_path, PANEL_TWEAKS, kept_copy=STOCK_PANEL)
    adopter = install_panel_patcher(tmp_path, BASE_LAYER, None, COLS_FRAGMENT)
    hand_over(tmp_path, adopter)
    after_first = _every_file_under(tmp_path)
    result = hand_over(tmp_path, adopter)
    assert result["ok"] is True
    assert _every_file_under(tmp_path) == after_first
    assert (kept_panel(adopter)).read_text() == STOCK_PANEL
    assert not (kept_panel(old_owner)).exists()
