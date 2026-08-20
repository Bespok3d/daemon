# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The handover under the conditions that break it: several old owners at once, a garbled kept copy,
an empty file on the printer, and the adopting plugin's own patch declaration.

Ownership of a printer file is handed over once and never audited afterwards, so a wrong
original adopted here is written back over the live file at the next uninstall. Every case below
asks the same question: does the new owner end up holding the true original, or does it refuse and
leave every copy where it was.
"""

import difflib
from pathlib import Path

import pytest

from core import jinni_client
from tests.core.packages.fake_panel_printer import (
    BASE_LAYER,
    COLS_FRAGMENT,
    PANEL,
    PANEL_TWEAKS,
    ROWS_FRAGMENT,
    STOCK_PANEL,
    hand_over,
    install_panel_patcher,
    kept_panel,
)

PANEL_COLOURS = "panel-colours"
BOTH_TWEAKS_APPLIED = "panel start\nrows: 8\ncols: 3\npanel end\n"
LANE_TOTAL = 60
LANE_SPACING = 7
BUSY_LANES = tuple(range(0, LANE_TOTAL, LANE_SPACING))


def _lanes_panel(busy_lanes: tuple[int, ...] = ()) -> str:
    """A panel long enough that many plugins patch it without touching each other's context."""
    return "".join(f"lane {lane}: {'busy' if lane in busy_lanes else 'idle'}\n"
                   for lane in range(LANE_TOTAL))


def _lane_fragment(lane: int) -> str:
    return "".join(difflib.unified_diff(
        _lanes_panel().splitlines(keepends=True),
        _lanes_panel((lane,)).splitlines(keepends=True),
        fromfile="a/panel.py", tofile="b/panel.py"))


@pytest.fixture(autouse=True)
def live_panel(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    device_files = {PANEL: BOTH_TWEAKS_APPLIED}
    monkeypatch.setattr(jinni_client, "variant_facts", dict)
    monkeypatch.setattr(jinni_client, "fetch", device_files.get)
    return device_files


def test_two_owners_patching_the_same_lines_refuse_the_handover_and_keep_every_copy(
        tmp_path: Path) -> None:
    """Two diffs that touch each other's context cannot both be proven off a copy, and an original
    that cannot be proven is the one thing that must never be adopted: it is written back over the
    live file the next time the new owner is uninstalled."""
    plugin_root = tmp_path / "plugins"
    tweaks = install_panel_patcher(plugin_root, PANEL_TWEAKS, STOCK_PANEL, ROWS_FRAGMENT)
    colours = install_panel_patcher(plugin_root, PANEL_COLOURS, STOCK_PANEL, COLS_FRAGMENT)
    adopter = install_panel_patcher(plugin_root, BASE_LAYER, None)

    result = hand_over(plugin_root, adopter)

    assert not result["ok"]
    assert not (kept_panel(adopter)).exists()
    assert (kept_panel(tweaks)).read_text() == STOCK_PANEL
    assert (kept_panel(colours)).read_text() == STOCK_PANEL


def test_a_kept_copy_the_printer_cannot_read_as_text_is_not_taken_for_the_original(
        tmp_path: Path, live_panel: dict[str, str]) -> None:
    live_panel[PANEL] = "panel start\nrows: 8\ncols: 2\npanel end\n"
    plugin_root = tmp_path / "plugins"
    garbled = install_panel_patcher(plugin_root, PANEL_TWEAKS, STOCK_PANEL)
    (kept_panel(garbled)).write_bytes(b"\xff\xfe\x00panel start\x00")
    adopter = install_panel_patcher(plugin_root, BASE_LAYER, None)

    result = hand_over(plugin_root, adopter)

    assert result["ok"], result["label"]
    assert (kept_panel(adopter)).read_text() == STOCK_PANEL


def test_an_empty_file_on_the_printer_is_never_adopted_as_the_original(
        tmp_path: Path, live_panel: dict[str, str]) -> None:
    live_panel[PANEL] = ""
    plugin_root = tmp_path / "plugins"
    adopter = install_panel_patcher(plugin_root, BASE_LAYER, None)

    result = hand_over(plugin_root, adopter)

    assert not result["ok"]
    assert not (kept_panel(adopter)).exists()


def test_the_adopting_plugins_own_patch_is_not_counted_as_already_on_the_file(
        tmp_path: Path, live_panel: dict[str, str]) -> None:
    live_panel[PANEL] = "panel start\nrows: 8\ncols: 2\npanel end\n"
    plugin_root = tmp_path / "plugins"
    install_panel_patcher(plugin_root, PANEL_TWEAKS, STOCK_PANEL)
    adopter = install_panel_patcher(plugin_root, BASE_LAYER, None)

    result = hand_over(plugin_root, adopter)

    assert result["ok"], result["label"]
    assert (kept_panel(adopter)).read_text() == STOCK_PANEL


def test_a_file_every_installed_plugin_patches_is_still_handed_over(
        tmp_path: Path, live_panel: dict[str, str]) -> None:
    live_panel[PANEL] = _lanes_panel(BUSY_LANES)
    plugin_root = tmp_path / "plugins"
    owners = [install_panel_patcher(plugin_root, f"lane-{lane}", _lanes_panel(),
                                    _lane_fragment(lane)) for lane in BUSY_LANES]
    adopter = install_panel_patcher(plugin_root, BASE_LAYER, None)

    result = hand_over(plugin_root, adopter)

    assert result["ok"], result["label"]
    assert (kept_panel(adopter)).read_text() == _lanes_panel()
    assert not any((kept_panel(owner)).exists() for owner in owners)
