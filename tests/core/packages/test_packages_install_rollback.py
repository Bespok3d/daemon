# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the single-package install path (installer.py, batch_one.py, batch_plan.py) must refuse or
survive, beyond the happy paths the rest of the suite already covers: a phase that fails without
raising, an exception raised after files already landed on disk, and a bad or absent input beside
good ones in the same batch call. The governing invariant is that the printer is never left broken:
a failed install must not scatter files it never finished applying, and a failure must show up as a
report, never as a silent gap.
"""

from pathlib import Path

import pytest

from core import jinni_client
from core.packages import batch_one, batch_plan, installer
from protocol import CommandEffect
from tests.package_fixtures import package_bytes

INSTALL_STUB: dict[str, list[object]] = {
    "dirs": [], "symlinks": [], "patches": [], "start": [], "templates": [],
}


def _package(tmp_path: Path, plugin_id: str, install: dict, members: dict[str, str]) -> Path:
    manifest = {"name": plugin_id, "version": "0.1.0", "install": install}
    package_path = tmp_path / f"{plugin_id}.b3"
    package_path.write_bytes(package_bytes(manifest, members))
    return package_path


def test_run_install_does_not_leave_the_extraction_behind_when_deps_were_never_baked(
    tmp_path: Path,
) -> None:
    """An install whose requirements.txt has no baked wheels must not leave its unpacked files
    sitting on the printer once the build is refused, the same as every other pre-phase refusal."""
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    members = {
        "files/settings.cfg": "owner: unbaked-deps-plugin\n",
        "requirements.txt": "somepkg==1.0\n",
    }
    package_path = _package(tmp_path, "unbaked-deps-plugin", INSTALL_STUB, members)

    with pytest.raises(ValueError, match="nothing was baked"):
        installer.run_install(plugin_root, package_path, {})

    plugin_dir = plugin_root / "unbaked-deps-plugin"
    assert not plugin_dir.exists()


def test_run_install_deactivates_a_plugin_whose_template_variable_was_never_declared(
    tmp_path: Path,
) -> None:
    """A template referencing a variable no manifest ever asked the user for must not render half
    filled, and the plugin must come off the system instead of sitting there quietly broken."""
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    template = {"from": "tmpl/settings.cfg.tmpl", "to": "settings.cfg"}
    install = {**INSTALL_STUB, "templates": [template]}
    members = {"tmpl/settings.cfg.tmpl": "owner: $UNDECLARED_OWNER\n"}
    package_path = _package(tmp_path, "undeclared-placeholder-plugin", install, members)

    plugin_id, log = installer.run_install(plugin_root, package_path, {})

    assert plugin_id == "undeclared-placeholder-plugin"
    template_phase = next(logged for logged in log if logged["id"] == "templates")
    assert template_phase["ok"] is False
    plugin_dir = plugin_root / "undeclared-placeholder-plugin"
    assert (plugin_dir / "deactivated.json").exists()
    assert not (plugin_dir / "settings.cfg").exists()


def _deferred_service_restart(expanded_cmds: list[str]) -> list[CommandEffect]:
    effect = CommandEffect(deferrable=True, restarts_services=(), blocking_token=None)
    return [effect for _ in expanded_cmds]


def test_apply_one_defers_no_restart_for_a_plugin_whose_install_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plugin whose install did not finish must never get its service restart batched in: that
    would bounce a service for a plugin that never actually landed."""
    monkeypatch.setattr(jinni_client, "classify_commands", _deferred_service_restart)
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    install = {
        **INSTALL_STUB,
        "templates": [{"from": "tmpl/settings.cfg.tmpl", "to": "settings.cfg"}],
        "start": ["restart-my-service"],
    }
    package_path = _package(
        tmp_path, "failed-phase-plugin", install,
        {"tmpl/settings.cfg.tmpl": "owner: $UNDECLARED_OWNER\n"},
    )

    result, deferred = batch_one.apply_one(plugin_root, {}, package_path, {}, lambda _phase: None)

    assert result["ok"] is False
    assert deferred == []


def test_plan_batch_keeps_the_good_package_when_a_sibling_file_is_unreadable(
    tmp_path: Path,
) -> None:
    """One corrupt upload in a multi-plugin call must cost only itself, not the plugins beside
    it."""
    good_path = _package(
        tmp_path, "good-plugin", INSTALL_STUB, {"files/settings.cfg": "owner: good-plugin\n"},
    )
    unreadable_path = tmp_path / "corrupt-plugin.b3"
    unreadable_path.write_bytes(b"not a real package")

    plan = batch_plan.plan_batch({}, [good_path, unreadable_path], {})

    assert "good-plugin" in plan.plugin_ids()
    assert "corrupt-plugin" in plan.unreadable


def test_plan_batch_refuses_only_the_plugin_with_an_unsafe_setting(tmp_path: Path) -> None:
    """One plugin's disallowed setting value must not cost its siblings, including the one the
    caller never supplied a setting for at all."""
    safe_path = _package(
        tmp_path, "safe-plugin", INSTALL_STUB, {"files/settings.cfg": "owner: safe-plugin\n"},
    )
    unsafe_path = _package(
        tmp_path, "unsafe-plugin", INSTALL_STUB, {"files/settings.cfg": "owner: unsafe-plugin\n"},
    )
    unasked_path = _package(
        tmp_path, "unasked-plugin", INSTALL_STUB, {"files/settings.cfg": "owner: unasked-plugin\n"},
    )
    vars_by_id = {
        "safe-plugin": {"NICKNAME": "front left"},
        "unsafe-plugin": {"NICKNAME": "front;left"},
    }

    plan = batch_plan.plan_batch({}, [safe_path, unsafe_path, unasked_path], vars_by_id)

    assert set(plan.refused) == {"unsafe-plugin"}
    assert plan.plugin_ids() == frozenset({"safe-plugin", "unsafe-plugin", "unasked-plugin"})
