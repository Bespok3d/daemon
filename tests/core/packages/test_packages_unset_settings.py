# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""No op ever writes a config file that still names a setting instead of holding its value.

A plugin's config template interpolates `$NAME`. If the value is missing the rendered file keeps the
literal `$NAME` text, and Klipper or Moonraker reads that at startup and stops. Every op path that
renders a template is covered here: a fresh install, a batched install or update, and a reconfigure.
"""
import json
from pathlib import Path

import pytest

from core import packages
from core.packages import errors, updater
from tests.package_fixtures import package_bytes

MP = pytest.MonkeyPatch

SPOOLMAN_TEMPLATE = "server: $SPOOLMAN_SERVER\nlogging: $SPOOLMAN_LOGGING\n"


def _spoolman_manifest(plugin_id: str = "spoolman") -> dict:
    """A package shaped like the real one that exposed this: one setting the plugin cannot run
    without, and one the plugin has its own answer for."""
    return {
        "name": plugin_id,
        "version": "0.1.0",
        "install": {
            "dirs": [], "symlinks": [], "patches": [], "start": [],
            "templates": [{"from": "files/spoolman.tmpl", "to": "files/spoolman.cfg"}],
        },
        "requires": {"variables": [
            {"name": "SPOOLMAN_SERVER", "required": True},
            {"name": "SPOOLMAN_LOGGING", "required": False, "default": "info"},
        ]},
    }


def _spoolman_package(tmp_path: Path, plugin_id: str = "spoolman") -> Path:
    package_path = tmp_path / f"{plugin_id}.b3"
    package_path.write_bytes(package_bytes(
        _spoolman_manifest(plugin_id), {"files/spoolman.tmpl": SPOOLMAN_TEMPLATE},
    ))
    return package_path


def test_install_is_refused_when_a_required_setting_arrived_empty(
    tmp_path: Path, monkeypatch: MP,
) -> None:
    plugin_root = tmp_path / "plugins"
    monkeypatch.setattr(packages, "PLUGIN_ROOT", plugin_root)

    with pytest.raises(packages.MissingSettingError) as refused:
        packages.install(_spoolman_package(tmp_path), {}, user_vars={})

    assert refused.value.missing == ["SPOOLMAN_SERVER"]


def test_a_refused_install_leaves_nothing_on_the_printer(
    tmp_path: Path, monkeypatch: MP,
) -> None:
    plugin_root = tmp_path / "plugins"
    monkeypatch.setattr(packages, "PLUGIN_ROOT", plugin_root)

    with pytest.raises(packages.MissingSettingError):
        packages.install(_spoolman_package(tmp_path), {}, user_vars={})

    assert not (plugin_root / "spoolman").exists()


def test_install_renders_the_manifest_default_for_a_setting_the_user_left_alone(
    tmp_path: Path, monkeypatch: MP,
) -> None:
    """The bug: an omitted optional setting was in no expansion table, so the printer's config read
    `logging: $SPOOLMAN_LOGGING`."""
    plugin_root = tmp_path / "plugins"
    monkeypatch.setattr(packages, "PLUGIN_ROOT", plugin_root)

    packages.install(
        _spoolman_package(tmp_path), {}, user_vars={"SPOOLMAN_SERVER": "http://spoolman:8000"},
    )

    rendered = (plugin_root / "spoolman" / "files" / "spoolman.cfg").read_text()
    assert rendered == "server: http://spoolman:8000\nlogging: info\n"


def test_an_install_persists_the_default_it_applied(tmp_path: Path, monkeypatch: MP) -> None:
    """Recover and update re-expand from what was persisted, so a default that only lived in memory
    would come back as the literal placeholder on the next re-apply."""
    plugin_root = tmp_path / "plugins"
    monkeypatch.setattr(packages, "PLUGIN_ROOT", plugin_root)

    packages.install(
        _spoolman_package(tmp_path), {}, user_vars={"SPOOLMAN_SERVER": "http://spoolman:8000"},
    )

    persisted = json.loads((plugin_root / "spoolman" / "user_vars.json").read_text())
    assert persisted["SPOOLMAN_LOGGING"] == "info"


def test_reconfigure_is_refused_when_a_required_setting_is_cleared(
    tmp_path: Path, monkeypatch: MP,
) -> None:
    plugin_root = tmp_path / "plugins"
    monkeypatch.setattr(packages, "PLUGIN_ROOT", plugin_root)
    packages.install(
        _spoolman_package(tmp_path), {}, user_vars={"SPOOLMAN_SERVER": "http://spoolman:8000"},
    )
    rendered = plugin_root / "spoolman" / "files" / "spoolman.cfg"
    before = rendered.read_text()

    with pytest.raises(packages.MissingSettingError):
        packages.reconfigure("spoolman", {}, {"SPOOLMAN_SERVER": ""})

    assert rendered.read_text() == before


def test_a_batched_install_refuses_the_package_and_keeps_going(
    tmp_path: Path, monkeypatch: MP,
) -> None:
    """One package arriving without a value it needs is that package's refusal, not the batch's."""
    plugin_root = tmp_path / "plugins"
    monkeypatch.setattr(packages, "PLUGIN_ROOT", plugin_root)
    unset = _spoolman_package(tmp_path, "spoolman")
    filled = _spoolman_package(tmp_path, "spoolman-two")

    results = updater.run_update_batch(
        plugin_root, {}, [unset, filled],
        {"spoolman-two": {"SPOOLMAN_SERVER": "http://spoolman:8000"}},
    )

    by_id = {result["plugin_id"]: result for result in results}
    assert by_id["spoolman"]["ok"] is False
    assert by_id["spoolman-two"]["ok"] is True
    assert not (plugin_root / "spoolman").exists()


def test_the_installer_refusal_is_the_one_the_api_turns_into_a_declined_install() -> None:
    """The daemon relays a reason as a token the client localizes, never as prose (ADR-0037)."""
    from api.routes.refusals import REFUSALS, refusal_detail

    refusal = packages.MissingSettingError("spoolman", ["SPOOLMAN_SERVER"])

    assert isinstance(refusal, REFUSALS)
    assert refusal_detail(refusal) == {
        "error": "missing_setting", "plugin_id": "spoolman", "missing": ["SPOOLMAN_SERVER"],
    }


def test_the_refusal_is_reexported_from_the_package_facade() -> None:
    assert packages.MissingSettingError is errors.MissingSettingError
