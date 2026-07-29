# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The deactivate/teardown lifecycle lives in core/packages/lifecycle.py: deactivate_all (the
reversible off-switch that keeps plugin files) and teardown (full uninstall + config-dir prune).
Editing the printer's own config and pruning its include dirs moved to the jinni (ADR-0037); the
end-to-end deactivate/teardown coverage (incl. include removal through the jinni) lives in
test_packages.py, and the include/config-dir contract is tested in the klipper-jinni gate."""

from core.packages import lifecycle


def test_lifecycle_module_exposes_deactivate_all_and_teardown() -> None:
    assert callable(lifecycle.deactivate_all)
    assert callable(lifecycle.teardown)
