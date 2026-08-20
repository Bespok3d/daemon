# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The printer refuses a package that asks for a newer daemon than it runs.

The app checks the same floor before it sends the package, but the app is not always the one
deciding: a sideloaded package, an older app, or a package published after the app shipped all reach
the printer with nobody having asked. Without this the package installs and quietly does nothing.
"""

import json
from pathlib import Path

import pytest

from api.routes.refusals import refusal_detail
from core.packages import archive
from core.packages.errors import IncompatiblePairError
from core.packages.pair_guard import DAEMON_SIDE, guard_daemon_reaches_the_package_floor
from tests.package_fixtures import package_bytes
from version import DAEMON_VERSION


def test_refuses_a_package_asking_for_a_newer_daemon() -> None:
    with pytest.raises(IncompatiblePairError) as refused:
        guard_daemon_reaches_the_package_floor({"min_daemon_version": "99.0.0"})
    assert refused.value.side == DAEMON_SIDE
    assert refused.value.required == "99.0.0"
    assert refused.value.running == DAEMON_VERSION


def test_the_refusal_tells_the_app_which_side_is_behind() -> None:
    """The daemon relays the facts and the app writes the sentence, so both sides are on the
    wire."""
    refused = IncompatiblePairError(DAEMON_SIDE, "99.0.0", DAEMON_VERSION)
    assert refusal_detail(refused) == {
        "error": "incompatible_pair",
        "side": "daemon",
        "required": "99.0.0",
        "running": DAEMON_VERSION,
    }


def test_accepts_a_package_asking_for_exactly_this_daemon() -> None:
    guard_daemon_reaches_the_package_floor({"min_daemon_version": DAEMON_VERSION})


def test_accepts_a_package_asking_for_an_older_daemon() -> None:
    guard_daemon_reaches_the_package_floor({"min_daemon_version": "0.0.1"})


def test_accepts_a_package_that_declares_no_floor() -> None:
    """Most packages name no floor at all, and every one of them still installs."""
    guard_daemon_reaches_the_package_floor({"name": "alpha", "version": "1.0"})


@pytest.mark.parametrize("unreadable", ["", "unknown", "1.2.beta", None])
def test_accepts_a_floor_it_cannot_read(unreadable: object) -> None:
    """An unreadable floor is a question the daemon could not ask, not a package proven wrong;
    refusing on it would take a working plugin away from its owner over a typo in a manifest."""
    guard_daemon_reaches_the_package_floor({"min_daemon_version": unreadable})


def test_the_floor_may_be_written_unquoted_in_the_manifest() -> None:
    """`"min_daemon_version": 0.9` reaches the daemon as a JSON number, and still compares."""
    with pytest.raises(IncompatiblePairError):
        guard_daemon_reaches_the_package_floor({"min_daemon_version": 99.0})


def test_unpack_refuses_before_a_byte_of_the_package_is_written(tmp_path: Path) -> None:
    package = tmp_path / "p.b3"
    package.write_bytes(package_bytes(
        {"name": "alpha", "version": "1.0", "min_daemon_version": "99.0.0",
         "install": {"start": []}},
        {"files/run.sh": "echo hi"},
    ))
    plugin_root = tmp_path / "plugins"
    with pytest.raises(IncompatiblePairError):
        archive.unpack_package(plugin_root, package)
    assert not (plugin_root / "alpha").exists()


def test_a_package_this_daemon_reaches_still_unpacks(tmp_path: Path) -> None:
    package = tmp_path / "p.b3"
    package.write_bytes(package_bytes(
        {"name": "alpha", "version": "1.0", "min_daemon_version": "0.0.1",
         "install": {"start": []}},
        {"files/run.sh": "echo hi"},
    ))
    manifest, plugin_dir, _file_count = archive.unpack_package(tmp_path / "plugins", package)
    assert json.loads((plugin_dir / "manifest.json").read_text())["name"] == "alpha"
    assert manifest["min_daemon_version"] == "0.0.1"
