# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The services row of a recover whose caller reboots the printer right after.

Restarting the core services one by one and then rebooting does the same work twice, and the
one-by-one wait is the slow part of a recover. When the caller says a reboot follows, the held
restarts are not run, and the row says so plainly instead of reading as if they had run.
"""
from ...results import SERVICES_PLUGIN_ID, item, phase

REBOOT_REPLACES_RESTART = "the printer reboot replaces the services restart"


def reboot_replaces_restart(held_restarts: list[str]) -> dict:
    """One services row naming each restart left to the reboot. Nothing ran, so nothing failed."""
    items = [item(f"left to the reboot: {command}", ok=True) for command in held_restarts]
    return {"plugin_id": SERVICES_PLUGIN_ID, "ok": True, "skipped": False,
            "reason": REBOOT_REPLACES_RESTART,
            "log": [phase("reboot-replaces-restart", REBOOT_REPLACES_RESTART, items)]}
