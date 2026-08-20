# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the printer is doing right now, asked of Moonraker, so no test ever interrupts a print."""
import httpx

MOONRAKER_PORT = 7125
MOONRAKER_TIMEOUT_SECONDS = 10.0
BUSY_PRINT_STATES = ("printing", "paused")
UNREACHABLE = "unreachable"


def print_state(printer_address: str) -> str:
    """The printer's own word for what it is doing, or "unreachable" when Moonraker does not
    answer."""
    try:
        answered = httpx.get(
            f"http://{printer_address}:{MOONRAKER_PORT}/printer/objects/query?print_stats",
            timeout=MOONRAKER_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError:
        return UNREACHABLE
    reported = answered.json().get("result", {}).get("status", {}).get("print_stats", {})
    return str(reported.get("state", ""))


def is_busy_printing(printer_address: str) -> bool:
    """True only when the printer is provably mid-print. A printer that cannot be asked is not
    called busy: the daemon refuses an install during a print on its own."""
    return print_state(printer_address) in BUSY_PRINT_STATES
