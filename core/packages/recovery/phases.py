# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A single-plugin operation's closing restart, told as install/reconfigure phases."""
from pathlib import Path

from ...results import item, phase
from ...safety import OperationContext
from .restart import restart_services


def restart_phases(plugin_root: Path, deferred_cmds: list[str], vars: dict[str, str],
                   ctx: OperationContext) -> list[dict]:
    """Restart the deferred core services THROUGH the safety net and return the outcome as
    install/reconfigure phases. A plugin that breaks Klipper/Moonraker is deactivated so the printer
    keeps working; the captured service log and what was disabled are surfaced as phases."""
    if not deferred_cmds:
        return []
    result = restart_services(plugin_root, deferred_cmds, vars, ctx)
    phases = list(result.get("log", []))
    deactivated = result.get("auto_deactivated")
    if not deactivated:
        return phases
    target_disabled = ctx.plugin_id in [name.strip() for name in deactivated.split(",")]
    detail = result.get("fix_detail", "")
    # State the FACT only; the app phrases user-facing advice per user tier and offers the report.
    if target_disabled:
        label = f"{ctx.plugin_id} was disabled to keep the printer working ({detail})."
    else:
        label = f"Disabled {deactivated} to keep the printer working ({detail})."
    phases.append(phase(
        "auto-recovery", "Safety auto-recovery",
        [item(label, ok=not target_disabled, output=result.get("failure_log", ""))],
    ))
    return phases
