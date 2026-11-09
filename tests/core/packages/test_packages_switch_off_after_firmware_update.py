# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Switching off or removing a plugin that patched a file, after a firmware update replaced it, puts
back the NEW firmware's file, never the old firmware's copy the plugin kept before the update.

Every way a plugin is switched off or removed outside a recovery is covered: on request, by the
safety net, all plugins at once, and a removal. The printer is the made-up panel printer."""
import json
import logging
from collections.abc import Callable
from pathlib import Path

import pytest

from core import jinni_client
from core.packages.deactivation import DEACTIVATED_MARKER
from core.packages.deactivator import deactivate_with_dependents, run_deactivate
from core.packages.lifecycle import deactivate_all
from core.packages.settle_originals import COPIES_REMOVED_UNCHECKED
from core.packages.switched_off_marker import AUTO_DEACTIVATED_PREFIX
from core.packages.uninstaller import run_uninstall
from tests.core.packages.fake_panel_printer import (
    PANEL_PATCHER,
    PLUGINS,
    STOCK_PANEL,
    TWEAKED_PANEL,
    patcher_holding_the_old_original,
)

FIRMWARE_UPDATE_LINE = "# a line the firmware update added\n"
NEW_FIRMWARE_PANEL = STOCK_PANEL + FIRMWARE_UPDATE_LINE
NEW_FIRMWARE_WITH_THE_TWEAK = TWEAKED_PANEL + FIRMWARE_UPDATE_LINE
# deactivate_all finds the plugins under the data root's own plugin folder.
DATA_ROOT_PLUGINS = Path("usr") / "local"
SwitchOff = Callable[[Path], object]
PANEL_STOP = "stop the panel"


def _switch_off_on_request(data_root: Path) -> object:
    return run_deactivate(data_root / DATA_ROOT_PLUGINS / PLUGINS, PANEL_PATCHER, {})


def _switch_off_by_the_safety_net(data_root: Path) -> object:
    return deactivate_with_dependents(data_root / DATA_ROOT_PLUGINS / PLUGINS, PANEL_PATCHER, {},
                                      f"{AUTO_DEACTIVATED_PREFIX}the printer did not start")


def _switch_off_everything(data_root: Path) -> object:
    deactivate_all({"BESPOK3D": str(data_root)})
    return None


def _remove(data_root: Path) -> object:
    return run_uninstall(data_root / DATA_ROOT_PLUGINS / PLUGINS, PANEL_PATCHER, {})


EVERY_WAY_OFF = [_switch_off_on_request, _switch_off_by_the_safety_net, _switch_off_everything,
                 _remove]


@pytest.fixture(autouse=True)
def printer_config_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    """Switching everything off also takes the include lines out of the printer's config: not what
    these tests look at."""
    monkeypatch.setattr(jinni_client, "remove_bespok3d_includes", lambda: None)


@pytest.mark.parametrize("switch_off", EVERY_WAY_OFF)
def test_the_new_firmware_file_comes_back_without_the_patch(tmp_path: Path,
                                                            switch_off: SwitchOff) -> None:
    _plugin_dir, _manifest, live_panel, _kept_panel = patcher_holding_the_old_original(
        tmp_path / DATA_ROOT_PLUGINS, NEW_FIRMWARE_WITH_THE_TWEAK, {})

    switch_off(tmp_path)

    assert live_panel.read_text() == NEW_FIRMWARE_PANEL


@pytest.mark.parametrize("switch_off", EVERY_WAY_OFF)
def test_without_a_firmware_update_the_kept_original_comes_back(tmp_path: Path,
                                                                switch_off: SwitchOff) -> None:
    _plugin_dir, _manifest, live_panel, _kept_panel = patcher_holding_the_old_original(
        tmp_path / DATA_ROOT_PLUGINS, TWEAKED_PANEL, {})

    switch_off(tmp_path)

    assert live_panel.read_text() == STOCK_PANEL


@pytest.mark.parametrize("switch_off", [_switch_off_on_request, _switch_off_by_the_safety_net])
def test_a_printer_error_during_the_check_still_switches_the_plugin_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, switch_off: SwitchOff,
) -> None:
    """The copy could not be checked, so it may be the old firmware's file: it is dropped and the
    file is left as it is, and the reason says why."""
    plugin_dir, _manifest, live_panel, kept_panel = patcher_holding_the_old_original(
        tmp_path / DATA_ROOT_PLUGINS, NEW_FIRMWARE_WITH_THE_TWEAK, {})
    monkeypatch.setattr(jinni_client, "fetch", _printer_not_answering)

    switched_off = switch_off(tmp_path)

    assert switched_off == [PANEL_PATCHER]
    reason = json.loads((plugin_dir / DEACTIVATED_MARKER).read_text())["reason"]
    assert COPIES_REMOVED_UNCHECKED in reason
    assert not kept_panel.exists()
    assert live_panel.read_text() == NEW_FIRMWARE_WITH_THE_TWEAK


def _printer_not_answering(_path: str) -> str | None:
    raise ConnectionError("the printer did not answer")


def test_a_printer_error_while_switching_everything_off_is_logged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """Switching everything off writes no reason per plugin, so the dropped copies are logged."""
    _plugin_dir, _manifest, live_panel, kept_panel = patcher_holding_the_old_original(
        tmp_path / DATA_ROOT_PLUGINS, NEW_FIRMWARE_WITH_THE_TWEAK, {})
    monkeypatch.setattr(jinni_client, "fetch", _printer_not_answering)

    with caplog.at_level(logging.WARNING):
        _switch_off_everything(tmp_path)

    assert not kept_panel.exists()
    assert live_panel.read_text() == NEW_FIRMWARE_WITH_THE_TWEAK
    assert f"{PANEL_PATCHER}: {COPIES_REMOVED_UNCHECKED}" in caplog.text


def test_a_printer_error_during_the_check_stops_a_removal_before_anything_is_taken_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin_dir, _manifest, live_panel, kept_panel = patcher_holding_the_old_original(
        tmp_path / DATA_ROOT_PLUGINS, NEW_FIRMWARE_WITH_THE_TWEAK, {"stop": [PANEL_STOP]})
    stops_run: list[list[str]] = []
    monkeypatch.setattr(jinni_client, "fetch", _printer_not_answering)
    monkeypatch.setattr(jinni_client, "run_actions", stops_run.append)

    with pytest.raises(ConnectionError):
        _remove(tmp_path)

    assert stops_run == []
    assert kept_panel.exists()
    assert live_panel.read_text() == NEW_FIRMWARE_WITH_THE_TWEAK
    assert plugin_dir.exists()
