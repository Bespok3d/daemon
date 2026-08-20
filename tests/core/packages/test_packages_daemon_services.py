# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A package can require a capability of the daemon itself, and an older daemon refuses it.

The daemon serves its own capabilities under service names. A package that needs one declares it the
same way it declares needing another plugin. A daemon build that does not serve that capability
finds nothing on the printer providing it and refuses the install, which is how a printer running an
older daemon is kept from accepting a package it could not honour.
"""

from pathlib import Path

import pytest

from core.packages import dependencies
from core.packages.daemon_services import MIGRATE_PATCH

BASE_PATCHER = "base-patcher"


def _needs_the_daemon_capability() -> dict:
    return {"name": BASE_PATCHER, "require": [{"service": MIGRATE_PATCH}]}


def test_a_package_requiring_a_daemon_capability_installs_on_this_daemon(tmp_path: Path) -> None:
    unmet = dependencies.unsatisfied_requirements(
        tmp_path, BASE_PATCHER, _needs_the_daemon_capability())

    assert unmet == []


def test_a_daemon_that_does_not_serve_it_refuses_the_package(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # An older daemon is exactly this: the capability is not in its list, and no plugin can supply
    # it, because the daemon is not installed in the plugin root at all.
    monkeypatch.setattr(dependencies, "DAEMON_SERVICES", frozenset())

    unmet = dependencies.unsatisfied_requirements(
        tmp_path, BASE_PATCHER, _needs_the_daemon_capability())

    assert unmet == [MIGRATE_PATCH]
