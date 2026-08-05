# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
import json
from pathlib import Path

import pytest

from core import selfcheck
from core.selfcheck import printer_state

MP = pytest.MonkeyPatch

WIRED_UP = {"printer.cfg": True, "moonraker.conf": True}
UNWIRED = {"printer.cfg": False, "moonraker.conf": False}


@pytest.fixture(autouse=True)
def _wired_up_printer(monkeypatch: MP) -> None:
    """Default the device answer to a printer whose own config includes us, so a test about links
    is not also a test about wiring. A test about wiring overrides this itself."""
    monkeypatch.setattr(printer_state.jinni_client, "bespok3d_include_status", lambda: WIRED_UP)


def _sound_tree(tmp_path: Path) -> Path:
    """A bespok3d tree with nothing wrong with it: both required directories, no plugins."""
    (tmp_path / "usr/local/plugins").mkdir(parents=True)
    (tmp_path / "etc/init.d/autostart").mkdir(parents=True)
    return tmp_path / "usr/local/plugins"


def _vars(tmp_path: Path) -> dict[str, str]:
    return {"BESPOK3D": str(tmp_path)}


def _make_plugin_with_symlink(
    plugin_root: Path,
    plugin_id: str,
    link_path: Path,
    deactivated: bool = False,
) -> Path:
    plugin_dir = plugin_root / plugin_id
    plugin_dir.mkdir(parents=True)
    source_file = plugin_dir / "files" / "mod.py"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("# source\n")
    manifest = {
        "name": plugin_id,
        "install": {
            "symlinks": [{"from": "files/mod.py", "to": str(link_path)}],
        },
    }
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest))
    if deactivated:
        (plugin_dir / "deactivated.json").write_text("{}")
    return plugin_dir


def test_selfcheck_reports_nothing_wrong_with_a_sound_printer_and_no_plugins(
    tmp_path: Path,
) -> None:
    _sound_tree(tmp_path)

    assert selfcheck.run_selfcheck(_vars(tmp_path)) == {
        "switched_off": False,
        "reboot_required": [],
        "problems": [],
        "drift": [],
    }


def test_selfcheck_reports_a_printer_that_no_longer_includes_bespok3d(
    tmp_path: Path, monkeypatch: MP
) -> None:
    # The junior case: no plugins left to drift, and the printer ignores bespok3d entirely.
    _sound_tree(tmp_path)
    monkeypatch.setattr(printer_state.jinni_client, "bespok3d_include_status", lambda: UNWIRED)

    report = selfcheck.run_selfcheck(_vars(tmp_path))

    assert [problem["detail"] for problem in report["problems"]] == [
        "moonraker.conf",
        "printer.cfg",
    ]
    assert {problem["kind"] for problem in report["problems"]} == {
        selfcheck.PROBLEM_INCLUDES_MISSING
    }


def test_selfcheck_reports_wiring_left_behind_on_a_switched_off_printer(
    tmp_path: Path, monkeypatch: MP
) -> None:
    _sound_tree(tmp_path)
    (tmp_path / "etc/deactivated").write_text("{}")
    monkeypatch.setattr(
        printer_state.jinni_client, "bespok3d_include_status", lambda: {"printer.cfg": True}
    )

    report = selfcheck.run_selfcheck(_vars(tmp_path))

    assert report["problems"] == [
        {
            "kind": selfcheck.PROBLEM_INCLUDES_PRESENT_WHILE_OFF,
            "detail": "printer.cfg",
            "plugin_id": None,
        }
    ]


def test_selfcheck_expects_no_wiring_on_a_switched_off_printer(
    tmp_path: Path, monkeypatch: MP
) -> None:
    _sound_tree(tmp_path)
    (tmp_path / "etc/deactivated").write_text("{}")
    monkeypatch.setattr(printer_state.jinni_client, "bespok3d_include_status", lambda: UNWIRED)

    assert selfcheck.run_selfcheck(_vars(tmp_path)) == {
        "switched_off": True,
        "reboot_required": [],
        "problems": [],
        "drift": [],
    }
    # Nothing is wrong here, and yet the printer has none of its wiring. A caller told only "no
    # problems" cannot tell this printer from a working one, so it shows nothing and leaves the user
    # with no way back on. That is how a switched-off printer read as a clean bill of health.


def test_selfcheck_leaves_a_switched_off_printers_unlinked_plugins_alone(
    tmp_path: Path, monkeypatch: MP
) -> None:
    plugin_root = _sound_tree(tmp_path)
    (tmp_path / "etc/deactivated").write_text("{}")
    monkeypatch.setattr(printer_state.jinni_client, "bespok3d_include_status", lambda: UNWIRED)
    _make_plugin_with_symlink(plugin_root, "sleeping-plugin", tmp_path / "extras" / "mod.py")

    assert selfcheck.run_selfcheck(_vars(tmp_path))["drift"] == []


def test_selfcheck_reports_a_missing_directory(tmp_path: Path) -> None:
    (tmp_path / "usr/local/plugins").mkdir(parents=True)

    report = selfcheck.run_selfcheck(_vars(tmp_path))

    assert report["problems"] == [
        {
            "kind": selfcheck.PROBLEM_DIRECTORY_MISSING,
            "detail": "etc/init.d/autostart",
            "plugin_id": None,
        }
    ]


def test_selfcheck_reports_a_plugin_left_half_removed(tmp_path: Path) -> None:
    plugin_root = _sound_tree(tmp_path)
    (plugin_root / "stump-plugin").mkdir()

    report = selfcheck.run_selfcheck(_vars(tmp_path))

    assert report["problems"] == [
        {
            "kind": selfcheck.PROBLEM_PLUGIN_HALF_REMOVED,
            "detail": "stump-plugin",
            "plugin_id": "stump-plugin",
        }
    ]


def test_selfcheck_reports_a_plugin_that_never_came_back(tmp_path: Path) -> None:
    plugin_root = _sound_tree(tmp_path)
    plugin_dir = _make_plugin_with_symlink(
        plugin_root, "stuck-plugin", tmp_path / "extras" / "mod.py"
    )
    (plugin_dir / "recovery_failure.json").write_text("{}")

    problems = selfcheck.run_selfcheck(_vars(tmp_path))["problems"]

    assert [problem["kind"] for problem in problems] == [selfcheck.PROBLEM_PLUGIN_RECOVERY_FAILED]


def test_selfcheck_reports_no_drift_when_every_symlink_is_correct(tmp_path: Path) -> None:
    plugin_root = _sound_tree(tmp_path)
    link_path = tmp_path / "extras" / "mod.py"
    link_path.parent.mkdir()
    plugin_dir = _make_plugin_with_symlink(plugin_root, "good-plugin", link_path)
    link_path.symlink_to((plugin_dir / "files" / "mod.py").resolve())

    assert selfcheck.run_selfcheck(_vars(tmp_path)) == {
        "switched_off": False,
        "reboot_required": [],
        "problems": [],
        "drift": [],
    }


def test_selfcheck_reports_missing_symlink(tmp_path: Path) -> None:
    plugin_root = _sound_tree(tmp_path)
    link_path = tmp_path / "extras" / "mod.py"
    link_path.parent.mkdir()
    _make_plugin_with_symlink(plugin_root, "missing-plugin", link_path)

    drift = selfcheck.run_selfcheck(_vars(tmp_path))["drift"]

    assert len(drift) == 1
    assert drift[0]["plugin_id"] == "missing-plugin"
    issues = drift[0]["symlink_issues"]
    assert len(issues) == 1
    assert issues[0]["kind"] == selfcheck.ISSUE_MISSING
    assert issues[0]["link_path"] == str(link_path)


def test_selfcheck_reports_wrong_target(tmp_path: Path) -> None:
    plugin_root = _sound_tree(tmp_path)
    link_path = tmp_path / "extras" / "mod.py"
    link_path.parent.mkdir()
    plugin_dir = _make_plugin_with_symlink(plugin_root, "drifted-plugin", link_path)
    rogue_target = tmp_path / "rogue.py"
    rogue_target.write_text("# rogue\n")
    link_path.symlink_to(rogue_target)

    drift = selfcheck.run_selfcheck(_vars(tmp_path))["drift"]

    assert len(drift) == 1
    issue = drift[0]["symlink_issues"][0]
    assert issue["kind"] == selfcheck.ISSUE_WRONG_TARGET
    assert issue["actual_target"] == str(rogue_target)
    assert issue["expected_target"] == str((plugin_dir / "files" / "mod.py").resolve())


def test_selfcheck_reports_when_path_is_not_a_symlink(tmp_path: Path) -> None:
    plugin_root = _sound_tree(tmp_path)
    link_path = tmp_path / "extras" / "mod.py"
    link_path.parent.mkdir()
    _make_plugin_with_symlink(plugin_root, "clobbered-plugin", link_path)
    link_path.write_text("# someone replaced the symlink with a regular file\n")

    drift = selfcheck.run_selfcheck(_vars(tmp_path))["drift"]

    assert len(drift) == 1
    issue = drift[0]["symlink_issues"][0]
    assert issue["kind"] == selfcheck.ISSUE_NOT_A_SYMLINK


def test_selfcheck_reports_a_boot_script_that_is_not_wired_in(tmp_path: Path) -> None:
    # A plugin whose boot script is not linked into autostart starts nothing after a reboot, which
    # is exactly as broken as a missing symlink and used to go unreported.
    plugin_root = _sound_tree(tmp_path)
    plugin_dir = plugin_root / "service-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "manifest.json").write_text(
        json.dumps(
            {
                "name": "service-plugin",
                "install": {"service": [{"name": "camera", "autostart": True}]},
            }
        )
    )

    drift = selfcheck.run_selfcheck(_vars(tmp_path))["drift"]

    assert len(drift) == 1
    assert drift[0]["symlink_issues"][0]["kind"] == selfcheck.ISSUE_MISSING


def test_selfcheck_skips_deactivated_plugins(tmp_path: Path) -> None:
    plugin_root = _sound_tree(tmp_path)
    link_path = tmp_path / "extras" / "mod.py"
    link_path.parent.mkdir()
    _make_plugin_with_symlink(plugin_root, "deactivated-plugin", link_path, deactivated=True)

    assert selfcheck.run_selfcheck(_vars(tmp_path)) == {
        "switched_off": False,
        "reboot_required": [],
        "problems": [],
        "drift": [],
    }


def test_selfcheck_uses_persisted_user_vars(tmp_path: Path) -> None:
    plugin_root = _sound_tree(tmp_path)
    plugin_id = "var-plugin"
    plugin_dir = plugin_root / plugin_id
    plugin_dir.mkdir()
    (plugin_dir / "files").mkdir()
    (plugin_dir / "files" / "mod.py").write_text("# src\n")
    extras_dir = tmp_path / "extras"
    extras_dir.mkdir()
    manifest = {
        "name": plugin_id,
        "install": {"symlinks": [{"from": "files/mod.py", "to": "$EXTRAS/mod.py"}]},
    }
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest))
    (plugin_dir / "user_vars.json").write_text(json.dumps({"EXTRAS": str(extras_dir)}))

    drift = selfcheck.run_selfcheck(_vars(tmp_path))["drift"]

    assert len(drift) == 1
    issue = drift[0]["symlink_issues"][0]
    assert issue["kind"] == selfcheck.ISSUE_MISSING
    assert issue["link_path"] == str(extras_dir / "mod.py")
