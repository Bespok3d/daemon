# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The safety net's report row: what it took off, and whether the printer came back."""

from ...results import SERVICES_PLUGIN_ID, item, phase
from ...safety import Decision, FailureEvidence, is_healthy
from .stranded import unsatisfied_reason


def recovery_result(deactivated: list[str], decision: Decision,
                    evidence: FailureEvidence, failure: FailureEvidence) -> dict:
    """Build the outcome. Health is judged on the FINAL evidence (did recovery work), but the
    reported log comes from the FIRST-failure evidence so the real traceback survives the recovery
    restarts that overwrite the live log."""
    ok = is_healthy(evidence)
    if deactivated:
        joined = ", ".join(deactivated)
        reason = (f"Auto-recovered: deactivated {joined} to keep the printer working" if ok
                  else f"Deactivated {joined} but the printer still did not recover")
    else:
        reason = decision.signal
    failure_log = failure.health.signals.log_tails
    safety_net_item = item(reason, ok=ok, output=failure_log)
    result = {"plugin_id": SERVICES_PLUGIN_ID, "ok": ok, "skipped": False, "reason": reason,
              "failure_log": failure_log,
              "log": [phase("safety-net", "Safety net recovery", [safety_net_item])]}
    if deactivated:
        result["auto_deactivated"] = ", ".join(deactivated)
        result["fix_detail"] = decision.signal
    return result


def stranded_report(restart_row: dict, stranded: dict[str, list[str]]) -> dict:
    """The restart's row, told after the plugins switched off before it because a plugin they need
    was off. They are named as the safety net's, so a batch row and the app say each was switched
    off, as if the net had found them after the restart."""
    if not stranded:
        return restart_row
    switched_off = ", ".join(stranded)
    detail = unsatisfied_reason(sorted({service for lost in stranded.values() for service in lost}))
    stranded_item = item(f"Switched off {switched_off}: {detail}", ok=True)
    stranded_phase = phase("stranded", "Plugins missing what they need", [stranded_item])
    return {**restart_row, "auto_deactivated": switched_off, "fix_detail": detail,
            "log": [stranded_phase, *restart_row["log"]]}


def with_net_report(restart_row: dict, net_row: dict) -> dict:
    """The safety net's verdict, after the restart's own items: they name the service that did not
    come back, which the net's restarts would otherwise hide. Plugins switched off before the
    restart stay named next to the ones the net took off."""
    rows = (restart_row, net_row)
    switched_off = [row["auto_deactivated"] for row in rows if row.get("auto_deactivated")]
    details = [row["fix_detail"] for row in rows if row.get("fix_detail")]
    merged = {**net_row, "log": [*restart_row["log"], *net_row["log"]]}
    if not switched_off:
        return merged
    return {**merged, "auto_deactivated": ", ".join(switched_off), "fix_detail": "; ".join(details)}
