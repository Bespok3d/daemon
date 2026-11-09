# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A plugin that takes a patched file over after a firmware update keeps the NEW firmware's file as
its original, never the old firmware's copy the previous owner kept.

This is the bench case: a second plugin took over the copy another plugin kept before the update to
firmware 2.1, so it patched the firmware 2.0 file, its 2.1 patch did not fit, and the printer was
left running a 2.0 file on 2.1 firmware."""
from pathlib import Path

import pytest

from core.packages.deactivation import DEACTIVATED_MARKER
from core.packages.manifest import manifest_at
from core.packages.patch_handover import NO_STOCK_ORIGINAL
from core.packages.recovery.reapply import ServiceLedger, recover_one
from tests.core.packages.fake_panel_printer import (
    BASE_LAYER,
    COLS_FRAGMENT,
    PANEL_TWEAKS,
    ROWS_FRAGMENT,
    STOCK_PANEL,
    install_panel_patcher,
    keep_stock_copy,
    kept_panel,
    patch_the_jinni_in,
    run_install,
    serve_panel,
)

FIRMWARE_UPDATE_LINE = "# a line the firmware update added\n"
NEW_FIRMWARE_PANEL = STOCK_PANEL + FIRMWARE_UPDATE_LINE
NEW_FIRMWARE_WITH_THE_TWEAK = "panel start\nrows: 8\ncols: 2\npanel end\n" + FIRMWARE_UPDATE_LINE
NEW_FIRMWARE_PANEL_WITH_COLS = "panel start\nrows: 4\ncols: 3\npanel end\n" + FIRMWARE_UPDATE_LINE
# The update changed a line inside the old owner's patch, so that patch neither fits the new panel
# nor comes off it.
RESHAPED_PANEL = "panel start\nrows: 4\nlanes: 2\ncols: 2\npanel end\n"
RESHAPED_PANEL_WITH_COLS = "panel start\nrows: 4\nlanes: 2\ncols: 3\npanel end\n"
COLS_FOR_THE_RESHAPED_PANEL = (
    "--- a/panel.py\n+++ b/panel.py\n@@ -1,5 +1,5 @@\n"
    " panel start\n rows: 4\n lanes: 2\n-cols: 2\n+cols: 3\n panel end\n"
)
SWITCHED_OFF = '{"reason": "switched off"}'
NOTHING_PROVIDED = ServiceLedger(set(), set())


@pytest.fixture(autouse=True)
def jinni(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_the_jinni_in(monkeypatch)


def _owner_holding_the_old_firmware_copy(printer_root: Path, live_panel_text: str,
                                         adopter_fragment: str) -> tuple[Path, Path, Path]:
    """A printer now serving `live_panel_text`, a plugin that patched the panel before the update
    and still holds the old firmware's copy, and a second plugin about to take the panel over."""
    live_panel = serve_panel(printer_root, live_panel_text)
    old_owner = install_panel_patcher(printer_root, PANEL_TWEAKS, kept_copy=None,
                                      fragment_text=ROWS_FRAGMENT, target=str(live_panel))
    keep_stock_copy(old_owner, str(live_panel), STOCK_PANEL)
    adopter = install_panel_patcher(printer_root, BASE_LAYER, kept_copy=None,
                                    fragment_text=adopter_fragment, target=str(live_panel))
    return live_panel, old_owner, adopter


def test_taking_over_a_patched_file_after_the_update_keeps_the_new_firmware_original(
    tmp_path: Path,
) -> None:
    """The old owner's patch is on the new file: it comes off, and what is left is the original."""
    live_panel, _old_owner, adopter = _owner_holding_the_old_firmware_copy(
        tmp_path, NEW_FIRMWARE_WITH_THE_TWEAK, COLS_FRAGMENT)

    phases = run_install(tmp_path, adopter)

    assert all(finished["ok"] for finished in phases)
    assert kept_panel(adopter, str(live_panel)).read_text() == NEW_FIRMWARE_PANEL
    assert live_panel.read_text() == NEW_FIRMWARE_PANEL_WITH_COLS


def test_taking_over_from_a_switched_off_plugin_after_the_update_keeps_the_new_firmware_file(
    tmp_path: Path,
) -> None:
    """Switched off, the old owner's patch is not on the file, even when it no longer fits it."""
    live_panel, old_owner, adopter = _owner_holding_the_old_firmware_copy(
        tmp_path, RESHAPED_PANEL, COLS_FOR_THE_RESHAPED_PANEL)
    (old_owner / DEACTIVATED_MARKER).write_text(SWITCHED_OFF)

    phases = run_install(tmp_path, adopter)

    assert all(finished["ok"] for finished in phases)
    assert kept_panel(adopter, str(live_panel)).read_text() == RESHAPED_PANEL
    assert live_panel.read_text() == RESHAPED_PANEL_WITH_COLS


def test_a_recovery_taking_over_after_the_update_keeps_the_new_firmware_file(
    tmp_path: Path,
) -> None:
    """In a recovery, a patch that neither fits the file nor comes off it was written for the
    firmware the printer ran before."""
    live_panel, _old_owner, adopter = _owner_holding_the_old_firmware_copy(
        tmp_path, RESHAPED_PANEL, COLS_FOR_THE_RESHAPED_PANEL)

    result, _deferred = recover_one(adopter, manifest_at(adopter), NOTHING_PROVIDED, {})

    assert result["ok"] is True
    assert kept_panel(adopter, str(live_panel)).read_text() == RESHAPED_PANEL
    assert live_panel.read_text() == RESHAPED_PANEL_WITH_COLS


def test_an_install_refuses_to_take_over_a_file_an_active_plugin_may_still_patch(
    tmp_path: Path,
) -> None:
    """Outside a recovery the old owner's patch may still be on the file in a shape that cannot be
    told apart, so nothing is adopted and the old owner keeps its copy and the file."""
    live_panel, old_owner, adopter = _owner_holding_the_old_firmware_copy(
        tmp_path, RESHAPED_PANEL, COLS_FOR_THE_RESHAPED_PANEL)

    phases = run_install(tmp_path, adopter)

    adopt_items = [entry["label"] for finished in phases if finished["id"] == "adopt"
                   for entry in finished["items"]]
    assert any(NO_STOCK_ORIGINAL in label for label in adopt_items)
    assert kept_panel(old_owner, str(live_panel)).read_text() == STOCK_PANEL
    assert live_panel.read_text() == RESHAPED_PANEL
