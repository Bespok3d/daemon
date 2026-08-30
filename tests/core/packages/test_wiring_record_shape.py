# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The daemon reads back exactly what the jinni writes into a plugin's wiring record.

The record is the jinni's format (ADR-0037 decision 6) and the daemon only reads it, so its shape is
declared once, in the jinni, and mirrored in `core/packages/wiring_record.py`. A mirror drifts in
silence: rename the key or the action word on the jinni's side and the daemon reads an empty record,
decides no plugin ever wrote anything, and stops putting patched files back on teardown. This drives
the jinni's own writer against the daemon's own reader, so the two cannot drift apart without a red
gate.

It stands down when the adapter tree is not checked out beside the daemon, because the daemon gates
on its own.
"""
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from core.packages import wiring_record

THE_JINNIS_RECORD_WRITER = (Path(__file__).resolve().parents[3].parent
                            / "adapters" / "klipper-jinni" / "jinni" / "reversion_record.py")
A_PANEL_THE_PRINTER_OWNS = "/opt/fakeprinter/ui/panel.py"
A_MENU_THE_PRINTER_OWNS = "/opt/fakeprinter/ui/menu.py"
A_TOOLHEAD_THE_PRINTER_OWNS = "/opt/fakeprinter/klipper/toolhead.py"
A_SYMLINK_THE_PLUGIN_LAID = "/opt/fakeprinter/config/tweaks.cfg"

pytestmark = pytest.mark.skipif(
    not THE_JINNIS_RECORD_WRITER.is_file(),
    reason="the jinni's own tree is not checked out beside the daemon",
)


@pytest.fixture
def jinni() -> ModuleType:
    """The jinni's own module, loaded from the adapter tree next door, so these tests assert against
    the code that really writes the record rather than against a copy of its rules."""
    spec = importlib.util.spec_from_file_location("jinni_reversion_record",
                                                  THE_JINNIS_RECORD_WRITER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _the_jinni_writes_a_printer_file(jinni: ModuleType, plugin_dir: Path, target: str) -> None:
    """The jinni overwriting one of the printer's own files for a plugin: it keeps the original and
    records how to put it back."""
    kept = plugin_dir / "patches_orig" / Path(target).name
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text("stock\n")
    jinni.merge_record(plugin_dir / jinni.WIRING_RECORD,
                       [jinni.reversion(Path(target), kept)])


def _the_jinni_lays_a_symlink(jinni: ModuleType, plugin_dir: Path, destination: str) -> None:
    """The jinni laying a link the printer did not have before: there is no original to keep, so the
    way back is to take the link away again."""
    plugin_dir.mkdir(parents=True, exist_ok=True)
    jinni.merge_record(plugin_dir / jinni.WIRING_RECORD,
                       [jinni.reversion(Path(destination), plugin_dir / "nothing-was-there")])


def test_the_daemon_reads_the_file_the_jinni_recorded_writing(
    tmp_path: Path, jinni: ModuleType,
) -> None:
    """The jinni wrote one of the printer's files and kept its original, so the daemon knows that
    file is this plugin's to put back."""
    plugin_dir = tmp_path / "panel-tweaks"

    _the_jinni_writes_a_printer_file(jinni, plugin_dir, A_PANEL_THE_PRINTER_OWNS)

    assert wiring_record.written_files(plugin_dir) == {A_PANEL_THE_PRINTER_OWNS}


def test_a_symlink_is_not_a_file_the_plugin_wrote(tmp_path: Path, jinni: ModuleType) -> None:
    """A step with no original behind it is a link the jinni laid, not a printer file it overwrote,
    so the daemon never writes anything over it."""
    plugin_dir = tmp_path / "panel-tweaks"

    _the_jinni_lays_a_symlink(jinni, plugin_dir, A_SYMLINK_THE_PLUGIN_LAID)

    assert wiring_record.written_files(plugin_dir) == set()


def test_the_jinni_keeps_reading_a_record_the_daemon_rewrote(
    tmp_path: Path, jinni: ModuleType,
) -> None:
    """The daemon rewrites the record when another plugin takes one of these files over, and the
    jinni goes on wiring the same plugin afterwards. The file handed over is gone, the other file
    this plugin wrote is untouched, and the file the jinni wired next is there."""
    plugin_dir = tmp_path / "panel-tweaks"
    _the_jinni_writes_a_printer_file(jinni, plugin_dir, A_PANEL_THE_PRINTER_OWNS)
    _the_jinni_writes_a_printer_file(jinni, plugin_dir, A_MENU_THE_PRINTER_OWNS)

    wiring_record.forget_written_file(plugin_dir, A_PANEL_THE_PRINTER_OWNS)
    _the_jinni_writes_a_printer_file(jinni, plugin_dir, A_TOOLHEAD_THE_PRINTER_OWNS)

    assert wiring_record.written_files(plugin_dir) == {A_MENU_THE_PRINTER_OWNS,
                                                      A_TOOLHEAD_THE_PRINTER_OWNS}


def test_the_daemon_names_the_record_and_its_actions_the_way_the_jinni_does(
    jinni: ModuleType,
) -> None:
    """The two names the daemon mirrors, held against the jinni's own."""
    assert wiring_record.WIRING_RECORD == jinni.WIRING_RECORD
    assert wiring_record.RESTORE_ACTION == jinni.REVERT_RESTORE
