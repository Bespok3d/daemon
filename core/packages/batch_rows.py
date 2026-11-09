# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The row a batch hands back for one plugin: the whole account the user gets of that plugin's
turn. A row has to end up saying what installing that plugin on its own would have said, which
includes the last word the single restart at the end of the batch has on it.
"""

from .batch_progress import BatchProgress


def install_error(failure: Exception) -> str:
    return f"install error: {type(failure).__name__}: {failure}"


def failed_result(plugin_id: str, reason: str, log: list[dict]) -> dict:
    return {"plugin_id": plugin_id, "ok": False, "skipped": False, "reason": reason, "log": log}


def _listed_as_switched_off(services_row: dict) -> list[str]:
    listed = str(services_row.get("auto_deactivated", ""))

    return [plugin_id.strip() for plugin_id in listed.split(",") if plugin_id.strip()]


def _switched_off(result: dict, signal: str) -> dict:
    return {
        **result,
        "ok": False,
        "auto_deactivated": result["plugin_id"],
        "reason": f"deactivated to keep the printer working: {signal}",
    }


def _after_the_restart(result: dict, switched_off: set[str], signal: str) -> dict:
    """A plugin the safety net switched off to keep the printer working is not installed and
    running, whatever its own row said before the batch reached its single restart. Installed on its
    own it would have been deactivated by the same net and reported as failed, so it says so too."""
    if result["plugin_id"] not in switched_off:
        return result

    return _switched_off(result, signal)


def settle_after_safety_net(
    results: list[dict], services_row: dict, progress: BatchProgress,
) -> list[dict]:
    """Give every plugin the outcome the end-of-batch restart left it with. The rows were written
    while the restarts were still deferred, so a plugin the net then switched off would otherwise
    still be reporting success for an install the printer has since undone. Its turn was already
    announced live as a success too, so its new outcome is announced again."""
    switched_off = set(_listed_as_switched_off(services_row))
    signal = str(services_row.get("fix_detail", ""))
    settled = [_after_the_restart(result, switched_off, signal) for result in results]
    for switched_off_row in [row for row in settled if row["plugin_id"] in switched_off]:
        progress.outcome(switched_off_row)

    return settled


def switched_off_rows(services_row: dict) -> list[dict]:
    """One row per plugin the safety net switched off, for a check that runs after the rows of the
    operation it checks were already handed back (the check after a reboot): the caller puts each
    one in place of that plugin's earlier row."""
    signal = str(services_row.get("fix_detail", ""))

    return [_switched_off(failed_result(plugin_id, "", []), signal)
            for plugin_id in _listed_as_switched_off(services_row)]
