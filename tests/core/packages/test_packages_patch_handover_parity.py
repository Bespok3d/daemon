# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A printer that hands a patched file over ends up with the file a fresh printer gets.

Two made-up printers, one panel file each. On the first, the base layer patches the panel outright.
On the second, another plugin patched it first and the base layer takes it over. Both must end up
holding the same original and serving the same panel, byte for byte, or a printer that migrated is
running something no fresh printer ever runs and no fix can be tested against it."""
from pathlib import Path

import pytest

from core import jinni_client
from core.packages.manifest import manifest_at
from core.packages.patches import apply_patches
from tests import fake_actuation
from tests.core.packages.fake_panel_printer import (
    BASE_LAYER,
    COLS_FRAGMENT,
    PANEL_NAME,
    PANEL_TWEAKS,
    ROWS_FRAGMENT,
    STOCK_PANEL,
    TWEAKED_PANEL,
    hand_over,
    install_panel_patcher,
    kept_panel,
)

PANEL_THE_BASE_LAYER_SERVES = "panel start\nrows: 4\ncols: 3\npanel end\n"


def _read_live_file(path: str) -> str | None:
    on_the_printer = Path(path)
    return on_the_printer.read_text() if on_the_printer.exists() else None


@pytest.fixture(autouse=True)
def jinni(monkeypatch: pytest.MonkeyPatch) -> None:
    """A jinni that reads and writes each fake printer's files where they really sit, so the two
    printers keep their own live panel instead of sharing one."""
    monkeypatch.setattr(jinni_client, "variant_facts", dict)
    monkeypatch.setattr(jinni_client, "fetch", _read_live_file)
    monkeypatch.setattr(jinni_client, "write_files", fake_actuation.write_files)


def _live_panel(printer_root: Path, panel_text: str) -> Path:
    """The panel this printer is serving right now."""
    live = printer_root / "device" / PANEL_NAME
    live.parent.mkdir(parents=True)
    live.write_text(panel_text)
    return live


def _install_plugin_patches(plugin_dir: Path) -> dict:
    """The plugin's install as the daemon runs it: the fragments its manifest declares, applied to
    the original it holds and written back to the printer."""
    return apply_patches(manifest_at(plugin_dir)["install"]["patches"], plugin_dir, {})


def test_a_printer_that_hands_the_panel_over_ends_up_with_the_fresh_printers_panel(
    tmp_path: Path,
) -> None:
    fresh_root = tmp_path / "fresh-printer"
    fresh_panel = _live_panel(fresh_root, STOCK_PANEL)
    fresh_owner = install_panel_patcher(fresh_root, BASE_LAYER, kept_copy=None,
                                        fragment_text=COLS_FRAGMENT, target=str(fresh_panel))
    assert _install_plugin_patches(fresh_owner)["ok"] is True

    handed_over_root = tmp_path / "handed-over-printer"
    handed_over_panel = _live_panel(handed_over_root, TWEAKED_PANEL)
    install_panel_patcher(handed_over_root, PANEL_TWEAKS, kept_copy=STOCK_PANEL,
                          fragment_text=ROWS_FRAGMENT, target=str(handed_over_panel))
    new_owner = install_panel_patcher(handed_over_root, BASE_LAYER, kept_copy=None,
                                      fragment_text=COLS_FRAGMENT,
                                      target=str(handed_over_panel))
    assert hand_over(handed_over_root, new_owner, str(handed_over_panel))["ok"] is True
    assert _install_plugin_patches(new_owner)["ok"] is True

    assert kept_panel(fresh_owner, str(fresh_panel)).read_text() == STOCK_PANEL
    assert kept_panel(new_owner, str(handed_over_panel)).read_text() == STOCK_PANEL
    assert fresh_panel.read_bytes() == handed_over_panel.read_bytes()
    assert fresh_panel.read_text() == PANEL_THE_BASE_LAYER_SERVES
