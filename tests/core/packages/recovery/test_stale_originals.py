# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A plugin recovery switches off after a firmware update must never put the old firmware's files
back: the copy it kept of a patched file is the OLD firmware's file once the update replaced it.

The printer is the made-up panel printer the patch tests share."""
import json
from pathlib import Path

import pytest

from core import jinni_client
from core.packages.baseline import stock_copies
from core.packages.deactivation import DEACTIVATED_MARKER
from core.packages.recovery.reapply import ServiceLedger, recover_one
from core.packages.recovery.run import run_recovery
from core.packages.settle_originals import COPIES_REMOVED_UNCHECKED, settle_kept_originals
from core.packages.uninstaller import remove_with_dependents
from core.packages.user_vars import USER_VARS_FILE
from core.packages.wiring_record import written_files
from tests.core.packages.fake_panel_printer import (
    PANEL_NAME,
    PANEL_PATCHER,
    PLUGINS,
    ROWS_FRAGMENT,
    STOCK_PANEL,
    TWEAKED_PANEL,
    patcher_holding_the_old_original,
)

FIRMWARE_UPDATE_LINE = "# a line the firmware update added\n"
NEW_FIRMWARE_PANEL = STOCK_PANEL + FIRMWARE_UPDATE_LINE
NEW_FIRMWARE_WITH_THE_TWEAK = TWEAKED_PANEL + FIRMWARE_UPDATE_LINE
USER_EDIT_LINE = "# a line the user added by hand\n"
TORN_FILE = "{ torn by a power cut"
NEEDS_RFID = {"require": [{"service": "rfid"}]}
NEEDS_A_SETTING = {"requires": {"variables": [{"name": "SPOOLMAN_SERVER", "required": True}]}}
PANEL_DIR_REQUIRED = {"name": "PANEL_DIR", "required": True}
SWITCHED_OFF = json.dumps({"reason": "switched off"})
RFID_NOT_BACK = ServiceLedger(set(), {"rfid"})
NOTHING_PROVIDED = ServiceLedger(set(), set())


def _panel_named_by(settings: list[dict]) -> dict:
    """The manifest fields of a plugin whose patched panel sits in the folder named by PANEL_DIR."""
    return {"requires": {"variables": settings},
            "install": {"patches": [{"file": f"$PANEL_DIR/{PANEL_NAME}",
                                     "patch": "patches/01-panel.patch"}]}}


def test_a_plugin_whose_provider_is_not_back_leaves_the_new_firmware_file_alone(
    tmp_path: Path,
) -> None:
    plugin_dir, manifest, live_panel, kept_panel = patcher_holding_the_old_original(
        tmp_path, NEW_FIRMWARE_PANEL, NEEDS_RFID)

    result, _deferred = recover_one(plugin_dir, manifest, RFID_NOT_BACK, {})

    assert result["skipped"] is True
    assert live_panel.read_text() == NEW_FIRMWARE_PANEL
    assert not kept_panel.exists()
    assert written_files(plugin_dir) == set()


def test_a_plugin_missing_a_setting_leaves_the_new_firmware_file_alone(tmp_path: Path) -> None:
    plugin_dir, manifest, live_panel, kept_panel = patcher_holding_the_old_original(
        tmp_path, NEW_FIRMWARE_PANEL, NEEDS_A_SETTING)

    result, _deferred = recover_one(plugin_dir, manifest, NOTHING_PROVIDED, {})

    assert result["ok"] is False
    assert live_panel.read_text() == NEW_FIRMWARE_PANEL
    assert not kept_panel.exists()
    assert written_files(plugin_dir) == set()


def test_a_file_the_update_did_not_replace_still_goes_back_to_its_original(tmp_path: Path) -> None:
    """The file still carries the plugin's patch, so its kept copy is still its true original."""
    plugin_dir, manifest, live_panel, kept_panel = patcher_holding_the_old_original(
        tmp_path, TWEAKED_PANEL, NEEDS_RFID)

    recover_one(plugin_dir, manifest, RFID_NOT_BACK, {})

    assert live_panel.read_text() == STOCK_PANEL
    assert kept_panel.read_text() == STOCK_PANEL
    assert written_files(plugin_dir) == {str(live_panel)}


def test_a_patched_new_firmware_file_goes_back_to_the_new_firmware_original(
    tmp_path: Path,
) -> None:
    """The plugin's patch comes off the new file: what is left is the new firmware's original."""
    plugin_dir, manifest, live_panel, kept_panel = patcher_holding_the_old_original(
        tmp_path, NEW_FIRMWARE_WITH_THE_TWEAK, NEEDS_RFID)

    recover_one(plugin_dir, manifest, RFID_NOT_BACK, {})

    assert live_panel.read_text() == NEW_FIRMWARE_PANEL
    assert kept_panel.read_text() == NEW_FIRMWARE_PANEL


def test_a_hand_edit_in_the_patched_file_survives_the_switch_off(tmp_path: Path) -> None:
    """Only the plugin's own change comes off the file: a line the user added stays."""
    plugin_dir, manifest, live_panel, _kept_panel = patcher_holding_the_old_original(
        tmp_path, TWEAKED_PANEL + USER_EDIT_LINE, NEEDS_RFID)

    recover_one(plugin_dir, manifest, RFID_NOT_BACK, {})

    assert live_panel.read_text() == STOCK_PANEL + USER_EDIT_LINE


def test_a_printer_error_during_the_check_drops_the_copies_and_names_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A copy that could not be checked may be the old firmware's file, so it is never written
    back; the switch-off still happens and the reason says why the copies are gone."""
    plugin_dir, manifest, live_panel, kept_panel = patcher_holding_the_old_original(
        tmp_path, NEW_FIRMWARE_PANEL, NEEDS_RFID)
    monkeypatch.setattr(jinni_client, "fetch", _printer_not_answering)

    result, _deferred = recover_one(plugin_dir, manifest, RFID_NOT_BACK, {})

    assert result["skipped"] is True
    assert COPIES_REMOVED_UNCHECKED in result["reason"]
    assert (plugin_dir / DEACTIVATED_MARKER).exists()
    assert live_panel.read_text() == NEW_FIRMWARE_PANEL
    assert not kept_panel.exists()


def _printer_not_answering(_path: str) -> str | None:
    raise ConnectionError("the printer did not answer")


def test_a_switch_off_for_a_missing_setting_finds_a_file_named_by_a_default_setting(
    tmp_path: Path,
) -> None:
    """The patched file's path is built from a setting the user never set but the plugin gives a
    default for: the switch-off must use that default too, or it never finds the file to undo."""
    panel_dir_setting = {"name": "PANEL_DIR", "default": str(tmp_path / "device")}
    needs = _panel_named_by([*NEEDS_A_SETTING["requires"]["variables"], panel_dir_setting])
    plugin_dir, manifest, live_panel, _kept_panel = patcher_holding_the_old_original(
        tmp_path, TWEAKED_PANEL, needs)

    recover_one(plugin_dir, manifest, NOTHING_PROVIDED, {})

    assert live_panel.read_text() == STOCK_PANEL


def test_a_file_named_by_the_missing_setting_drops_its_copy(tmp_path: Path) -> None:
    """The setting that names the patched file has no value, so the file cannot be found to check
    its copy. The copy is dropped, or the reinstall the reason asks for would patch it."""
    plugin_dir, manifest, live_panel, kept_panel = patcher_holding_the_old_original(
        tmp_path, NEW_FIRMWARE_PANEL, _panel_named_by([PANEL_DIR_REQUIRED]))

    result, _deferred = recover_one(plugin_dir, manifest, NOTHING_PROVIDED, {})

    assert COPIES_REMOVED_UNCHECKED in result["reason"]
    assert not kept_panel.exists()
    assert live_panel.read_text() == NEW_FIRMWARE_PANEL


def test_a_missing_setting_whose_name_starts_a_longer_one_is_not_taken_for_it(
    tmp_path: Path,
) -> None:
    """PANEL is missing and PANEL_DIR names the file: the file is still found and settled."""
    panel_dir_setting = {"name": "PANEL_DIR", "default": str(tmp_path / "device")}
    needs = _panel_named_by([{"name": "PANEL", "required": True}, panel_dir_setting])
    plugin_dir, manifest, live_panel, _kept_panel = patcher_holding_the_old_original(
        tmp_path, NEW_FIRMWARE_WITH_THE_TWEAK, needs)

    result, _deferred = recover_one(plugin_dir, manifest, NOTHING_PROVIDED, {})

    assert COPIES_REMOVED_UNCHECKED not in result["reason"]
    assert live_panel.read_text() == NEW_FIRMWARE_PANEL


def test_a_copy_kept_under_a_name_two_patched_files_share_is_left_alone(tmp_path: Path) -> None:
    """An older daemon kept copies under the bare file name. When the plugin patches two files of
    that name, the copy cannot say which one it came from, so nothing about it can be checked."""
    plugin_dir, manifest, _live_panel, kept_panel = patcher_holding_the_old_original(
        tmp_path, NEW_FIRMWARE_PANEL, {})
    skin_panel = tmp_path / "skin" / PANEL_NAME
    skin_panel.parent.mkdir()
    skin_panel.write_text(NEW_FIRMWARE_WITH_THE_TWEAK)
    (plugin_dir / "patches" / "02-skin.patch").write_text(ROWS_FRAGMENT)
    skin_patch = {"file": str(skin_panel), "patch": "patches/02-skin.patch"}
    manifest["install"]["patches"].append(skin_patch)
    bare_copy = stock_copies(plugin_dir) / PANEL_NAME
    kept_panel.rename(bare_copy)

    settle_kept_originals(plugin_dir, manifest, {})

    assert bare_copy.read_text() == STOCK_PANEL


@pytest.mark.parametrize("recovered_first", [True, False])
def test_removing_a_plugin_switched_off_before_the_update_leaves_the_new_firmware_file_alone(
    tmp_path: Path, recovered_first: bool,
) -> None:
    """The plugin put its original back when it was switched off, then the update replaced the
    file. Removing the plugin afterwards must not write the old firmware's copy over it, whether a
    recovery ran in between or not."""
    plugin_dir, _manifest, live_panel, _kept_panel = patcher_holding_the_old_original(
        tmp_path, NEW_FIRMWARE_PANEL, {})
    (plugin_dir / DEACTIVATED_MARKER).write_text(SWITCHED_OFF)

    if recovered_first:
        run_recovery(tmp_path / "data", tmp_path / PLUGINS, {})
    remove_with_dependents(tmp_path / PLUGINS, PANEL_PATCHER, {}, [])

    assert live_panel.read_text() == NEW_FIRMWARE_PANEL


def test_a_plugin_switched_off_on_a_file_the_update_did_not_touch_keeps_its_original(
    tmp_path: Path,
) -> None:
    """Switched off, the plugin's patch is already off the file: the file is its kept original."""
    plugin_dir, _manifest, _live_panel, kept_panel = patcher_holding_the_old_original(
        tmp_path, STOCK_PANEL, {})
    (plugin_dir / DEACTIVATED_MARKER).write_text(SWITCHED_OFF)

    run_recovery(tmp_path / "data", tmp_path / PLUGINS, {})

    assert kept_panel.read_text() == STOCK_PANEL


def test_a_switched_off_plugin_that_cannot_be_checked_is_reported_and_recovery_goes_on(
    tmp_path: Path,
) -> None:
    plugin_dir, _manifest, _live_panel, kept_panel = patcher_holding_the_old_original(
        tmp_path, NEW_FIRMWARE_PANEL, {})
    (plugin_dir / DEACTIVATED_MARKER).write_text(SWITCHED_OFF)
    (plugin_dir / USER_VARS_FILE).write_text(TORN_FILE)

    results = run_recovery(tmp_path / "data", tmp_path / PLUGINS, {})

    assert [(row["plugin_id"], row["ok"]) for row in results] == [(PANEL_PATCHER, False)]
    assert COPIES_REMOVED_UNCHECKED in results[0]["reason"]
    assert not kept_panel.exists()


def test_a_switched_off_plugin_is_reported_once_for_copies_it_no_longer_has(tmp_path: Path) -> None:
    """Its copies were dropped by the first recovery, so the next one has nothing left to check."""
    plugin_dir, _manifest, _live_panel, _kept_panel = patcher_holding_the_old_original(
        tmp_path, NEW_FIRMWARE_PANEL, _panel_named_by([PANEL_DIR_REQUIRED]))
    (plugin_dir / DEACTIVATED_MARKER).write_text(SWITCHED_OFF)

    first_results = run_recovery(tmp_path / "data", tmp_path / PLUGINS, {})
    next_results = run_recovery(tmp_path / "data", tmp_path / PLUGINS, {})

    assert [row["plugin_id"] for row in first_results] == [PANEL_PATCHER]
    assert next_results == []


def test_a_switched_off_plugin_finds_a_file_named_by_a_default_setting(tmp_path: Path) -> None:
    """The user never set PANEL_DIR, so the copy is checked against the file the default names: the
    old firmware's copy is found and dropped. Without the default no file is found and it stays."""
    panel_dir_setting = {"name": "PANEL_DIR", "default": str(tmp_path / "device")}
    plugin_dir, _manifest, _live_panel, kept_panel = patcher_holding_the_old_original(
        tmp_path, NEW_FIRMWARE_PANEL, _panel_named_by([panel_dir_setting]))
    (plugin_dir / DEACTIVATED_MARKER).write_text(SWITCHED_OFF)

    results = run_recovery(tmp_path / "data", tmp_path / PLUGINS, {})

    assert results == []
    assert not kept_panel.exists()


@pytest.mark.parametrize("switched_off_before", [False, True])
def test_a_plugin_with_a_torn_manifest_never_puts_the_old_firmware_file_back(
    tmp_path: Path, switched_off_before: bool,
) -> None:
    """A torn manifest names no patches, so no copy can be checked: they are dropped, and removing
    the plugin later leaves the new firmware's file alone."""
    plugin_dir, _manifest, live_panel, kept_panel = patcher_holding_the_old_original(
        tmp_path, NEW_FIRMWARE_PANEL, {})
    if switched_off_before:
        (plugin_dir / DEACTIVATED_MARKER).write_text(SWITCHED_OFF)
    (plugin_dir / "manifest.json").write_text(TORN_FILE)

    run_recovery(tmp_path / "data", tmp_path / PLUGINS, {})
    remove_with_dependents(tmp_path / PLUGINS, PANEL_PATCHER, {}, [])

    assert not kept_panel.exists()
    assert live_panel.read_text() == NEW_FIRMWARE_PANEL
