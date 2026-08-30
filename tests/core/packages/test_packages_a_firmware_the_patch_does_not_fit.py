# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A printer whose firmware moved the file a base member patches, mid migration.

The base layer ships one patch per firmware it knows about, chosen by a version floor with no
ceiling, so a firmware newer than any the package was built for still picks the newest patch it
has. When the vendor has since edited that file, the patch no longer fits, and the base member is
refused on a printer the user is in the middle of migrating.

That refusal is the right answer, and these tests hold it to the promise the user is owed with it:
the panel the printer serves is the one the vendor shipped, everything the printer already had
still works, and nothing is left behind for the user to clean up. A refused base member costs the
user one plugin, never the printer."""
import json
from pathlib import Path

import pytest

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
)

PANEL_A_NEWER_FIRMWARE_SERVES = "panel start\nrows: 4\ncolumns: 2\npanel end\n"
LITTER_A_FAILED_PATCH_LEAVES = ("*.rej", "*.orig", "*.b3work")


@pytest.fixture(autouse=True)
def jinni(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_the_jinni_in(monkeypatch)


def _serve_a_panel_the_vendor_has_changed(printer_root: Path) -> Path:
    """The printer takes a firmware update, and the file the base member patches is not the file
    the base member was built against: the line its patch needs for context is gone."""
    return serve_panel(printer_root, PANEL_A_NEWER_FIRMWARE_SERVES)


def _a_base_member_built_for_the_old_firmware(printer_root: Path, live_panel: Path) -> Path:
    return install_panel_patcher(printer_root, BASE_LAYER, kept_copy=None,
                                 fragment_text=COLS_FRAGMENT, target=str(live_panel))


def _the_plugin_the_printer_already_had(printer_root: Path) -> tuple[Path, Path]:
    """A plugin the user installed long before the migration, patching a file of its own, already
    applied and running. The migration must not cost the user this."""
    its_file = printer_root / "device" / "tweaked.py"
    its_file.write_text(STOCK_PANEL)
    plugin_dir = install_panel_patcher(printer_root, PANEL_TWEAKS, kept_copy=None,
                                       fragment_text=ROWS_FRAGMENT, target=str(its_file))
    keep_stock_copy(plugin_dir, str(its_file), STOCK_PANEL)
    run_install(printer_root, plugin_dir)
    return plugin_dir, its_file


def test_a_base_member_whose_patch_does_not_fit_this_firmware_is_refused(tmp_path: Path) -> None:
    """The install fails rather than writing a partway result, and the refusal names the file the
    user has to be told about."""
    printer_root = tmp_path / "printer-on-a-newer-firmware"
    live_panel = _serve_a_panel_the_vendor_has_changed(printer_root)

    phases = run_install(printer_root, _a_base_member_built_for_the_old_firmware(
        printer_root, live_panel))

    assert not all(finished["ok"] for finished in phases)
    refused = [finished for finished in phases if not finished["ok"]]
    assert live_panel.name in json.dumps(refused)


def test_a_base_member_that_does_not_fit_leaves_the_vendors_own_panel_running(
    tmp_path: Path,
) -> None:
    """The printer keeps serving exactly the file the firmware put there, so the user's next print
    behaves the way it did before they pressed install."""
    printer_root = tmp_path / "printer-on-a-newer-firmware"
    live_panel = _serve_a_panel_the_vendor_has_changed(printer_root)

    run_install(printer_root, _a_base_member_built_for_the_old_firmware(printer_root, live_panel))

    assert live_panel.read_text() == PANEL_A_NEWER_FIRMWARE_SERVES


def test_the_plugin_the_printer_already_had_still_runs_after_a_base_member_is_refused(
    tmp_path: Path,
) -> None:
    """One base member the firmware outgrew must not take the user's working plugins down with it:
    its patch is still on its file, and it still holds the original it would put back."""
    printer_root = tmp_path / "printer-on-a-newer-firmware"
    live_panel = _serve_a_panel_the_vendor_has_changed(printer_root)
    already_installed, its_file = _the_plugin_the_printer_already_had(printer_root)

    run_install(printer_root, _a_base_member_built_for_the_old_firmware(printer_root, live_panel))

    assert its_file.read_text() == TWEAKED_PANEL
    assert kept_panel(already_installed, str(its_file)).read_text() == STOCK_PANEL


def test_a_refused_base_member_leaves_nothing_for_the_user_to_clean_up(tmp_path: Path) -> None:
    """No reject file, no half-written working copy, nothing the user has to find and delete before
    the printer will take the base member once a patch that fits it ships."""
    printer_root = tmp_path / "printer-on-a-newer-firmware"
    live_panel = _serve_a_panel_the_vendor_has_changed(printer_root)
    _the_plugin_the_printer_already_had(printer_root)

    run_install(printer_root, _a_base_member_built_for_the_old_firmware(printer_root, live_panel))

    left_behind = [str(found) for pattern in LITTER_A_FAILED_PATCH_LEAVES
                   for found in printer_root.rglob(pattern)]
    assert left_behind == []
