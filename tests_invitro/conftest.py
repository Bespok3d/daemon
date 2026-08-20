# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What every in-vitro test is handed: a real printer's address, its daemon, and an idle printer.

Nothing here runs without B3D_HIL_HOST naming a printer; without it the whole suite skips, so the
repo gate stays a desk gate. A test that changes the printer carries the `mutating` marker, puts
back what it changed, and never runs while a print is on.
"""
import os
from collections.abc import Iterator

import pytest

from tests_invitro import print_activity
from tests_invitro.daemon_wire import DaemonWire, printer_token

MUTATING_MARKER = (
    "mutating: installs a package on the printer; run it with B3D_INVITRO_MUTATE=1 "
    "through scripts/invitro.sh"
)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", MUTATING_MARKER)


@pytest.fixture(scope="session")
def printer_address() -> str:
    address = os.environ.get("B3D_HIL_HOST", "")
    if not address:
        pytest.skip("set B3D_HIL_HOST to the printer's address; this suite drives a real printer")
    return address


@pytest.fixture(scope="session")
def printer_daemon(printer_address: str) -> Iterator[DaemonWire]:
    daemon = DaemonWire(printer_address, printer_token(printer_address))
    yield daemon
    daemon.close()


@pytest.fixture
def idle_printer(printer_address: str) -> None:
    if print_activity.is_busy_printing(printer_address):
        pytest.skip("the printer is mid-print; nothing here interrupts a print")
