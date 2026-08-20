# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The batched multi-plugin INSTALL entry point ("install selected"): apply each package's install
phases and restart each affected service once at the end. The apply-and-defer machinery lives in
`batch.py` and what the printer will not accept in `batch_refusals.py`; this drives the two as an
install. Collapsing N restarts into one is what keeps a multi-plugin install from bouncing the U1
display compositor once per display plugin.
"""

from pathlib import Path

from ..safety import OperationKind
from .batch import run_batch
from .batch_plan import plan_batch
from .batch_progress import ProgressSink, make_progress
from .batch_refusals import settle_refusals


def run_install_batch(
    plugin_root: Path,
    base_vars: dict[str, str],
    package_paths: list[Path],
    vars_by_id: dict[str, dict[str, str]],
    publish: ProgressSink | None = None,
) -> list[dict]:
    """Install several plugins at once, restarting affected services only once at the end.

    The same apply-and-defer engine as the batched update, reported to the safety net as an install.
    """
    if not package_paths:
        return []
    progress = make_progress(publish)
    plan = plan_batch(base_vars, package_paths, vars_by_id)
    settled = settle_refusals(plugin_root, plan, package_paths)

    return run_batch(plugin_root, settled, progress, OperationKind.INSTALL)
