# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Four packages a real printer must turn away, each on its own reason, with nothing left behind.

None of these needs the mutating marker: a refused package is never installed, and every test here
proves the printer holds no directory for it afterwards.
"""
from http import HTTPStatus

from tests_invitro import probe_packages
from tests_invitro.daemon_wire import DaemonWire


def test_package_asking_for_a_daemon_no_printer_runs(
    printer_daemon: DaemonWire, idle_printer: None,
) -> None:
    answered = printer_daemon.offer_package(
        probe_packages.package_asking_for_a_daemon_no_printer_runs(),
    )

    assert answered.status_code == HTTPStatus.CONFLICT
    assert probe_packages.DAEMON_FLOOR_NO_PRINTER_MEETS in answered.text
    assert not printer_daemon.plugin_files_on_disk(probe_packages.PROBE_PLUGIN_ID)


def test_package_declaring_more_bytes_than_the_flash_holds(
    printer_daemon: DaemonWire, idle_printer: None,
) -> None:
    answered = printer_daemon.offer_package(
        probe_packages.package_declaring_more_bytes_than_the_flash_holds(),
    )

    assert answered.status_code == HTTPStatus.BAD_REQUEST
    assert "MB unpacked" in answered.text
    assert not printer_daemon.plugin_files_on_disk(probe_packages.PROBE_PLUGIN_ID)


def test_package_declaring_python_deps_it_never_baked(
    printer_daemon: DaemonWire, idle_printer: None,
) -> None:
    answered = printer_daemon.offer_package(
        probe_packages.package_declaring_python_deps_it_never_baked(),
    )

    assert answered.status_code == HTTPStatus.BAD_REQUEST
    assert probe_packages.REQUIREMENTS_MEMBER in answered.text
    assert not printer_daemon.plugin_files_on_disk(probe_packages.PROBE_PLUGIN_ID)


def test_package_whose_member_unpacks_to_more_than_it_declared(
    printer_daemon: DaemonWire, idle_printer: None,
) -> None:
    """The only refusal here that the printer cannot make before it starts writing."""
    answered = printer_daemon.offer_package(
        probe_packages.package_whose_member_unpacks_to_more_than_it_declared(),
    )

    assert answered.status_code == HTTPStatus.BAD_REQUEST
    assert "did not unpack" in answered.text
    assert not printer_daemon.plugin_files_on_disk(probe_packages.PROBE_PLUGIN_ID)
