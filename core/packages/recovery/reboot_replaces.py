# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The services row of a recover whose caller reboots the printer right after, and the safety net
check that the reboot would otherwise skip.

Restarting the core services one by one and then rebooting does the same work twice, and the
one-by-one wait is the slow part of a recover. When the caller says a reboot follows, the held
restarts are not run, and the row says so plainly instead of reading as if they had run. The held
restarts are kept on disk, so once the printer is back the caller asks for the check the net would
have made after those restarts, and a plugin that breaks the printer is still taken off.
"""
import json
import os
from pathlib import Path

from ...results import SERVICES_PLUGIN_ID, item, phase
from ...safety import OperationContext, OperationKind
from ..batch_rows import switched_off_rows
from ..print_guard import guard_no_print
from .restart import safety_net_check, touches_core_service

REBOOT_REPLACES_RESTART = "the printer reboot replaces the services restart"
HEALTHY_AFTER_REBOOT = "the printer came back healthy after the reboot"
RESTARTS_LEFT_TO_REBOOT = "etc/daemon/restarts-left-to-reboot.json"


def leave_restarts_to_reboot(data_root: Path, held_restarts: list[str]) -> dict:
    """Keep the held restarts for the check after the reboot, and return one services row naming
    each of them. Nothing ran, so nothing failed."""
    _save_held_restarts(data_root / RESTARTS_LEFT_TO_REBOOT, held_restarts)
    items = [item(f"left to the reboot: {command}", ok=True) for command in held_restarts]
    return {"plugin_id": SERVICES_PLUGIN_ID, "ok": True, "skipped": False,
            "reason": REBOOT_REPLACES_RESTART,
            "log": [phase("reboot-replaces-restart", REBOOT_REPLACES_RESTART, items)]}


def check_after_reboot(data_root: Path, plugin_root: Path, vars: dict[str, str]) -> list[dict]:
    """The safety net check for the restarts a recover left to the reboot: no rows when none were
    left or none of them restarts a core service, otherwise one row for each plugin the net
    switched off and then the services row. The kept restarts are spent once the check has run, so
    a later call never checks an old recover a second time; a check that fails or is refused during
    a print keeps them for the next call."""
    marker = data_root / RESTARTS_LEFT_TO_REBOOT
    if not marker.exists():
        return []
    guard_no_print()
    rows = _check_held_restarts(plugin_root, json.loads(marker.read_text()), vars)
    marker.unlink(missing_ok=True)
    return rows


def forget_restarts_left_to_reboot(data_root: Path) -> None:
    """A new recover replaces whatever an earlier one left to a reboot that never asked back."""
    (data_root / RESTARTS_LEFT_TO_REBOOT).unlink(missing_ok=True)


def _check_held_restarts(plugin_root: Path, held_restarts: list[str],
                         vars: dict[str, str]) -> list[dict]:
    """The same rule as a restart done in place: only a core service puts the printer at risk."""
    if not touches_core_service(held_restarts):
        return []
    recovered = safety_net_check(plugin_root, held_restarts, vars,
                                 OperationContext(OperationKind.RECOVER))
    if recovered is None:
        return [_healthy_row()]

    return [*switched_off_rows(recovered), recovered]


def _healthy_row() -> dict:
    return {"plugin_id": SERVICES_PLUGIN_ID, "ok": True, "skipped": False,
            "reason": HEALTHY_AFTER_REBOOT,
            "log": [phase("after-reboot", HEALTHY_AFTER_REBOOT,
                          [item(HEALTHY_AFTER_REBOOT, ok=True)])]}


def _save_held_restarts(marker: Path, held_restarts: list[str]) -> None:
    """Written whole or not at all, and on the flash before the reboot that follows: a half-written
    or lost list would leave the check after the reboot unable to run. The directory is synced too,
    or the rename itself may not survive the reboot."""
    marker.parent.mkdir(parents=True, exist_ok=True)
    staging = marker.with_suffix(".tmp")
    with staging.open("w") as staged:
        staged.write(json.dumps(held_restarts))
        staged.flush()
        os.fsync(staged.fileno())
    os.replace(staging, marker)
    directory = os.open(marker.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
