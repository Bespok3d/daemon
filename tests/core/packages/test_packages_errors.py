# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The package-install errors have a canonical home in core.packages.errors and stay reachable from
the core.packages namespace, where api.routes and the rest of the suite reference them as
packages.ConflictError / packages.DependentsError."""
from core import packages
from core.packages import errors


def test_errors_reexported_from_package_namespace() -> None:
    assert errors.ConflictError is packages.ConflictError
    assert errors.DependentsError is packages.DependentsError
    assert errors.RequirementError is packages.RequirementError


def test_conflict_error_carries_plugin_and_conflicts() -> None:
    error = errors.ConflictError("camera", ["rfid", "spoolman"])
    assert error.plugin_id == "camera"
    assert error.conflicts == ["rfid", "spoolman"]
    assert "conflicts with installed" in str(error)


def test_dependents_error_carries_plugin_and_dependents() -> None:
    error = errors.DependentsError("rfid", ["spoolman"])
    assert error.plugin_id == "rfid"
    assert error.dependents == ["spoolman"]
    assert "is required by" in str(error)


def test_requirement_error_carries_plugin_and_missing_services() -> None:
    error = errors.RequirementError("zerotier", ["tun"])
    assert error.plugin_id == "zerotier"
    assert error.missing == ["tun"]
    assert "requires uninstalled service" in str(error)
