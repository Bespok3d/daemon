# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""An install that takes a file over and then fails leaves the printer exactly as it found it.

This is the migration's worst day: the base layer adopts the panel a plugin has been patching for
months, and then its own patch does not fit and the install fails. The printer must come out of that
with the plugin still patching the panel it always patched and still holding the only way back to
stock. Both promises were broken at once on the bench: the old owner's copy was taken at adopt time
and went down with the failed install, and switching the failed plugin off wrote its adopted copy
over a live file it had never touched, stripping the plugin's patch off a working printer."""
from pathlib import Path

import pytest

from core.packages.extraction import discard_if_first_install
from tests.core.packages.fake_panel_printer import (
    BASE_LAYER,
    COLS_FRAGMENT,
    PANEL_NAME,
    PANEL_TWEAKS,
    ROWS_FRAGMENT,
    STOCK_PANEL,
    TWEAKED_PANEL,
    install_panel_patcher,
    keep_stock_copy,
    kept_panel,
    patch_the_jinni_in,
    run_install,
    serve_panel,
)

A_FRAGMENT_NO_PANEL_FITS = (
    "--- a/panel.py\n+++ b/panel.py\n@@ -1,4 +1,4 @@\n"
    " panel start\n-lanes: 2\n+lanes: 6\n cols: 2\n panel end\n"
)


@pytest.fixture(autouse=True)
def jinni(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_the_jinni_in(monkeypatch)


def _a_migration_that_fails_after_adopting(printer_root: Path) -> tuple[Path, Path, Path]:
    """A printer serving the plugin's panel, and a base layer that takes the panel over and then
    fails on its own patch: the failing first install, run and settled the way the daemon runs it.

    The base layer's diff fits no panel at all, so the file is adopted and the patch phase fails
    right after, which is the shape both bench failures had."""
    live_panel = serve_panel(printer_root, TWEAKED_PANEL)
    patcher = install_panel_patcher(printer_root, PANEL_TWEAKS, kept_copy=None,
                                    fragment_text=ROWS_FRAGMENT, target=str(live_panel))
    keep_stock_copy(patcher, str(live_panel), STOCK_PANEL)
    base_layer = install_panel_patcher(printer_root, BASE_LAYER, kept_copy=None,
                                       fragment_text=A_FRAGMENT_NO_PANEL_FITS,
                                       target=str(live_panel))
    phases = run_install(printer_root, base_layer)
    discard_if_first_install(base_layer, replacing_an_install=False)
    assert not all(finished["ok"] for finished in phases), "the install was meant to fail"
    return live_panel, patcher, base_layer


def test_a_failed_takeover_leaves_the_old_owner_holding_the_panels_original(
    tmp_path: Path,
) -> None:
    """The printer keeps its way back to stock. Committing the hand-over at adopt time took the
    plugin's copy before the install was known to work, and the base layer's own copy went with its
    failed install, so the panel had no original left on the printer at all."""
    live_panel, patcher, base_layer = _a_migration_that_fails_after_adopting(tmp_path / "printer")

    assert kept_panel(patcher, str(live_panel)).read_text() == STOCK_PANEL
    assert not base_layer.exists()


def test_a_failed_takeover_leaves_the_plugins_panel_running_on_the_printer(tmp_path: Path) -> None:
    """The plugin the user installed keeps working. Switching the failed base layer off used to
    write its adopted stock copy over the live panel, a file the base layer had never written,
    which took the plugin's change off a printer that was working a moment earlier."""
    live_panel, _patcher, _base_layer = _a_migration_that_fails_after_adopting(tmp_path / "printer")

    assert live_panel.read_text() == TWEAKED_PANEL


_DELETE = Path.unlink


def _a_printer_with_no_room_for_the_tidy_up(self: Path, missing_ok: bool = False) -> None:
    """A printer that will not let the old owner's copy of the panel go, the way a full or read-only
    /userdata answers. Every other delete goes through, so the install itself runs normally."""
    if self.name == PANEL_NAME and PANEL_TWEAKS in self.parts:
        raise OSError("no space left on device")
    _DELETE(self, missing_ok=missing_ok)


def test_a_copy_that_will_not_go_does_not_take_a_finished_install_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Letting the old owner go is tidy-up, not the job: a printer that refuses it still reports the
    install that worked as worked, and simply keeps the copy it would not let go of."""
    printer_root = tmp_path / "printer-with-no-room"
    live_panel = serve_panel(printer_root, TWEAKED_PANEL)
    patcher = install_panel_patcher(printer_root, PANEL_TWEAKS, kept_copy=None,
                                    fragment_text=ROWS_FRAGMENT, target=str(live_panel))
    keep_stock_copy(patcher, str(live_panel), STOCK_PANEL)
    base_layer = install_panel_patcher(printer_root, BASE_LAYER, kept_copy=None,
                                       fragment_text=COLS_FRAGMENT, target=str(live_panel))
    monkeypatch.setattr(Path, "unlink", _a_printer_with_no_room_for_the_tidy_up)

    phases = run_install(printer_root, base_layer)

    assert all(finished["ok"] for finished in phases)
    assert kept_panel(patcher, str(live_panel)).read_text() == STOCK_PANEL
    assert kept_panel(base_layer, str(live_panel)).read_text() == STOCK_PANEL
