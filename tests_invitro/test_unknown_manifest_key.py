# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A manifest key written after this daemon shipped must not stop the package installing.

A store package outlives the daemon reading it, so an unknown key is ignored, never a refusal. This
one really installs, so it carries the mutating marker and takes itself off the printer again.
"""
from collections.abc import Iterator
from http import HTTPStatus

import pytest

from tests_invitro import probe_packages
from tests_invitro.daemon_wire import DaemonWire

INSTALL_TIMEOUT_SECONDS = 300


@pytest.fixture
def probe_taken_off_afterwards(printer_daemon: DaemonWire) -> Iterator[None]:
    yield
    printer_daemon.uninstall(probe_packages.PROBE_PLUGIN_ID)


@pytest.mark.mutating
@pytest.mark.timeout(INSTALL_TIMEOUT_SECONDS)
def test_package_carrying_a_manifest_key_the_daemon_does_not_know(
    printer_daemon: DaemonWire, idle_printer: None, probe_taken_off_afterwards: None,
) -> None:
    answered = printer_daemon.offer_package(
        probe_packages.package_carrying_a_manifest_key_the_daemon_does_not_know(),
    )

    assert answered.status_code == HTTPStatus.OK
    assert answered.json()["ok"] is True
    installed = printer_daemon.installed_versions()
    assert installed.get(probe_packages.PROBE_PLUGIN_ID) == probe_packages.PROBE_VERSION

    removed = printer_daemon.uninstall(probe_packages.PROBE_PLUGIN_ID)

    assert removed.status_code == HTTPStatus.OK
    assert probe_packages.PROBE_PLUGIN_ID not in printer_daemon.installed_versions()
    assert not printer_daemon.plugin_files_on_disk(probe_packages.PROBE_PLUGIN_ID)
