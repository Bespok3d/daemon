# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A printer that already lost a plugin's stock original gets it back, and is never stripped mean-
while.

Printers in the field ran the version that let a plugin's original go the moment another plugin
claimed the file, instead of waiting for that install to settle. On one of those, a plugin can be
patching a file it no longer holds the original of. These hold the two things that owner needs to be
true: nothing on that printer is quietly stripped while it is in that state, and the next install,
update or recovery of the plugin puts its original back with no intervention from him.
"""
import json
from pathlib import Path

import pytest

from core.packages import patch_reversion
from core.packages.wiring_record import RESTORE_ACTION, WIRING_RECORD
from tests.core.packages.fake_panel_printer import (
    PANEL_TWEAKS,
    ROWS_FRAGMENT,
    STOCK_PANEL,
    TWEAKED_PANEL,
    install_panel_patcher,
    kept_panel,
    patch_the_jinni_in,
    run_install,
    serve_panel,
)


@pytest.fixture(autouse=True)
def jinni(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_the_jinni_in(monkeypatch)


def _a_plugin_that_lost_its_original(printer_root: Path, live_panel: Path) -> Path:
    """A plugin as one of those printers holds it: its patch is on the panel and the jinni's record
    says it wrote the panel, but the copy that record points at is gone."""
    patcher = install_panel_patcher(printer_root, PANEL_TWEAKS, kept_copy=None,
                                    fragment_text=ROWS_FRAGMENT, target=str(live_panel))
    (patcher / WIRING_RECORD).write_text(json.dumps({"reversions": [
        {"path": str(live_panel), "action": RESTORE_ACTION,
         "backup": str(kept_panel(patcher, str(live_panel)))},
    ]}))
    return patcher


def _the_panel_patch(plugin_dir: Path) -> list[dict]:
    return list(json.loads((plugin_dir / "manifest.json").read_text())["install"]["patches"])


def test_the_next_run_puts_the_lost_original_back(tmp_path: Path) -> None:
    """The repair: installing, updating or recovering the plugin takes the panel's original back off
    the live panel and keeps it again, so the printer has its way back to stock without the owner
    doing anything."""
    printer_root = tmp_path / "printer-from-the-field"
    live_panel = serve_panel(printer_root, TWEAKED_PANEL)
    patcher = _a_plugin_that_lost_its_original(printer_root, live_panel)

    phases = run_install(printer_root, patcher)

    assert all(finished["ok"] for finished in phases)
    assert kept_panel(patcher, str(live_panel)).read_text() == STOCK_PANEL
    assert live_panel.read_text() == TWEAKED_PANEL


def test_a_plugin_with_no_original_left_leaves_the_panel_alone(tmp_path: Path) -> None:
    """Until that repair runs, taking the plugin off writes nothing over the panel: there is no copy
    to write, and a printer serving a panel is better off than one served a blank."""
    printer_root = tmp_path / "printer-from-the-field"
    live_panel = serve_panel(printer_root, TWEAKED_PANEL)
    patcher = _a_plugin_that_lost_its_original(printer_root, live_panel)

    patch_reversion.revert_patched_files(patcher, _the_panel_patch(patcher), {})

    assert live_panel.read_text() == TWEAKED_PANEL
