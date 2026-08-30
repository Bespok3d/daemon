# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A printer whose panel one plugin patches ends up with the base layer patching it, by itself.

The hand-over runs as part of a plugin's ordinary install, so a printer migrates by installing and
updating the way it always does. These tests drive the install the daemon really runs, on a made-up
printer with one panel file, and hold it to what the migration promises: the printer ends on the
base layer's panel, no original is ever released before the file it describes is safe, the end state
does not depend on which package arrives first, and a printer cut off mid migration still has a
panel to start on."""
import json
from pathlib import Path

import pytest

from core import jinni_client
from core.packages import installer
from tests import fake_actuation
from tests.core.packages.fake_panel_printer import (
    BASE_LAYER,
    COLS_FRAGMENT,
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
    stop_patching,
)

PANEL_THE_BASE_LAYER_SERVES = "panel start\nrows: 4\ncols: 3\npanel end\n"
A_PANEL_NO_FRAGMENT_FITS = "panel start\nrows: 9\ncols: 2\npanel end\n"
COMPLETE_PANELS = (STOCK_PANEL, TWEAKED_PANEL, PANEL_THE_BASE_LAYER_SERVES)


def _refuse_to_write(plugin_dir: str, writes: list[dict]) -> list[fake_actuation.ActionResult]:
    """A printer that will not take the write, the way a filesystem with no room left answers."""
    return [fake_actuation.ActionResult(ok=False, output="no space left on device")
            for _refused in writes]


@pytest.fixture(autouse=True)
def jinni(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_the_jinni_in(monkeypatch)


def _phase(phases: list[dict], phase_id: str) -> dict:
    """The named phase of an install the caller has just asserted ran."""
    return next(finished for finished in phases if finished["id"] == phase_id)


def _phases_run(phases: list[dict]) -> list[str]:
    return [finished["id"] for finished in phases]


def _panel_tweaks_patching(printer_root: Path, live_panel: Path, kept: str) -> Path:
    """The plugin that patches the panel today, holding its copy of the original."""
    patcher = install_panel_patcher(printer_root, PANEL_TWEAKS, kept_copy=None,
                                    fragment_text=ROWS_FRAGMENT, target=str(live_panel))
    keep_stock_copy(patcher, str(live_panel), kept)
    return patcher


def _base_layer_taking_over(printer_root: Path, live_panel: Path) -> Path:
    """The base layer, shipping the panel patch of its own."""
    return install_panel_patcher(printer_root, BASE_LAYER, kept_copy=None,
                                 fragment_text=COLS_FRAGMENT, target=str(live_panel))


def test_a_printer_already_patched_by_a_plugin_ends_on_the_base_layers_panel(
    tmp_path: Path,
) -> None:
    """R-MIGR-1: the plugin's change is gone from the panel the printer serves, and the base layer
    holds the panel's true original rather than the plugin's output."""
    printer_root = tmp_path / "migrating-printer"
    live_panel = serve_panel(printer_root, TWEAKED_PANEL)
    patcher = _panel_tweaks_patching(printer_root, live_panel, kept=STOCK_PANEL)

    phases = run_install(printer_root, _base_layer_taking_over(printer_root, live_panel))

    assert all(finished["ok"] for finished in phases)
    assert live_panel.read_text() == PANEL_THE_BASE_LAYER_SERVES
    assert kept_panel(_base_layer_dir(printer_root), str(live_panel)).read_text() == STOCK_PANEL
    assert not kept_panel(patcher, str(live_panel)).exists()


def _base_layer_dir(printer_root: Path) -> Path:
    return printer_root / BASE_LAYER


def test_a_plugin_that_stops_patching_puts_the_panel_back_before_it_lets_the_original_go(
    tmp_path: Path,
) -> None:
    """R-MIGR-2, the promise kept: the update that drops the patch writes the original back over
    the panel, and only then stops holding a copy of it."""
    printer_root = tmp_path / "printer"
    live_panel = serve_panel(printer_root, TWEAKED_PANEL)
    patcher = _panel_tweaks_patching(printer_root, live_panel, kept=STOCK_PANEL)
    stop_patching(patcher)

    phases = run_install(printer_root, patcher)

    assert _phase(phases, "relinquish")["ok"] is True
    assert live_panel.read_text() == STOCK_PANEL
    assert not kept_panel(patcher, str(live_panel)).exists()


def test_a_plugin_that_cannot_write_the_panel_back_keeps_holding_the_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R-MIGR-2, the promise under failure: a printer that refused the write still has the only
    copy of the original, so the panel can still be put back on the next run."""
    printer_root = tmp_path / "printer"
    live_panel = serve_panel(printer_root, TWEAKED_PANEL)
    patcher = _panel_tweaks_patching(printer_root, live_panel, kept=STOCK_PANEL)
    stop_patching(patcher)
    monkeypatch.setattr(jinni_client, "write_files", _refuse_to_write)

    phases = run_install(printer_root, patcher)

    assert _phase(phases, "relinquish")["ok"] is False
    assert "patches" not in _phases_run(phases)
    assert kept_panel(patcher, str(live_panel)).read_text() == STOCK_PANEL
    assert live_panel.read_text() == TWEAKED_PANEL


def test_the_base_layer_refuses_a_panel_whose_original_it_cannot_establish(
    tmp_path: Path,
) -> None:
    """A panel nobody can prove the original of stops the install before a single fragment lands,
    so the printer keeps the panel it is running and the plugin keeps its copy."""
    printer_root = tmp_path / "printer"
    live_panel = serve_panel(printer_root, A_PANEL_NO_FRAGMENT_FITS)
    patcher = _panel_tweaks_patching(printer_root, live_panel, kept=TWEAKED_PANEL)

    phases = run_install(printer_root, _base_layer_taking_over(printer_root, live_panel))

    assert _phase(phases, "adopt")["ok"] is False
    assert "patches" not in _phases_run(phases)
    assert live_panel.read_text() == A_PANEL_NO_FRAGMENT_FITS
    assert kept_panel(patcher, str(live_panel)).read_text() == TWEAKED_PANEL


def _migrate_base_layer_first(printer_root: Path) -> Path:
    """The base layer arrives while the plugin still patches the panel, and the plugin's update
    that stops patching lands afterwards."""
    live_panel = serve_panel(printer_root, TWEAKED_PANEL)
    patcher = _panel_tweaks_patching(printer_root, live_panel, kept=STOCK_PANEL)
    run_install(printer_root, _base_layer_taking_over(printer_root, live_panel))
    stop_patching(patcher)
    run_install(printer_root, patcher)
    return live_panel


def _migrate_plugin_update_first(printer_root: Path) -> Path:
    """The plugin's update that stops patching lands first, and the base layer arrives after it."""
    live_panel = serve_panel(printer_root, TWEAKED_PANEL)
    patcher = _panel_tweaks_patching(printer_root, live_panel, kept=STOCK_PANEL)
    stop_patching(patcher)
    run_install(printer_root, patcher)
    run_install(printer_root, _base_layer_taking_over(printer_root, live_panel))
    return live_panel


def test_the_migration_ends_the_same_whichever_package_arrives_first(tmp_path: Path) -> None:
    """R-MIGR-3: two printers migrate in opposite orders and end up serving the same panel, with
    the panel's true original in the base layer's hands on both."""
    base_first_root = tmp_path / "base-layer-first"
    plugin_first_root = tmp_path / "plugin-update-first"

    base_first_panel = _migrate_base_layer_first(base_first_root)
    plugin_first_panel = _migrate_plugin_update_first(plugin_first_root)

    assert base_first_panel.read_bytes() == plugin_first_panel.read_bytes()
    assert base_first_panel.read_text() == PANEL_THE_BASE_LAYER_SERVES
    for printer_root, panel in ((base_first_root, base_first_panel),
                                (plugin_first_root, plugin_first_panel)):
        assert kept_panel(_base_layer_dir(printer_root), str(panel)).read_text() == STOCK_PANEL


class _PowerCutError(Exception):
    """The printer losing power the moment a phase finishes."""


def _cut_the_power_after(phase_id: str) -> installer.PhaseListener:
    def listener(finished: dict) -> None:
        if finished["id"] == phase_id:
            raise _PowerCutError

    return listener


@pytest.mark.parametrize("cut_after", ["symlinks", "relinquish", "adopt", "patches"])
def test_a_printer_cut_off_mid_migration_still_has_a_panel_to_start_on(
    tmp_path: Path, cut_after: str,
) -> None:
    """R-MIGR-4: whichever step the migration is cut at, the panel on the printer is a whole panel,
    never a blank or half-written one, and the original is still on the printer to finish with."""
    printer_root = tmp_path / "printer"
    live_panel = serve_panel(printer_root, TWEAKED_PANEL)
    patcher = _panel_tweaks_patching(printer_root, live_panel, kept=STOCK_PANEL)
    base_layer = _base_layer_taking_over(printer_root, live_panel)

    with pytest.raises(_PowerCutError):
        run_install(printer_root, base_layer, _cut_the_power_after(cut_after))

    assert live_panel.read_text() in COMPLETE_PANELS
    held = [kept_panel(plugin_dir, str(live_panel)) for plugin_dir in (patcher, base_layer)]
    still_on_the_printer = [kept.read_text() for kept in held if kept.exists()]
    assert still_on_the_printer
    assert set(still_on_the_printer) == {STOCK_PANEL}


def test_the_wiring_reads_the_manifest_the_printer_holds(tmp_path: Path) -> None:
    """The plugin's own manifest is what says which files it patches, so a printer with no patching
    plugin on it runs the hand-over phases and changes nothing."""
    printer_root = tmp_path / "printer"
    printer_root.mkdir()
    plugin_dir = printer_root / "no-patches"
    plugin_dir.mkdir()
    (plugin_dir / "manifest.json").write_text(json.dumps({"id": "no-patches", "install": {}}))

    phases = run_install(printer_root, plugin_dir)

    assert _phase(phases, "relinquish")["items"] == []
    assert _phase(phases, "adopt")["items"] == []
