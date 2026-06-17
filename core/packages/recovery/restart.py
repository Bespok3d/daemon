"""Drive the core.safety decision brain during a deferred core-service restart.

The safety net (core.safety) decides; this module acts: it runs the restart, gathers the evidence,
asks the brain who broke the printer, deactivates that plugin, and restarts again, surfacing the
outcome as install/reconfigure phases. This is what keeps a printer usable after an OTA firmware
update: a plugin that breaks against the new firmware peels itself off until a fixed version is
published. It runs on every operation that restarts a core service, not only recover.
"""

from pathlib import Path

from ... import jinni_client
from ...results import SERVICES_PLUGIN_ID, item, phase
from ...safety import (
    Decision,
    FailureEvidence,
    OperationContext,
    OperationKind,
    decide,
    is_healthy,
)
from ...safety.restart_batch import run_restart_batch
from ..deactivation import deactivate_plugin
from ..manifest import installed_manifest_dirs
from .evidence import gather_evidence


def op_context(kind: OperationKind, manifest: dict, plugin_id: str | None = None) -> OperationContext:  # noqa: E501
    """The operation the daemon is performing, for the safety net's report + last-resort blame."""
    return OperationContext(
        kind=kind,
        plugin_id=plugin_id if plugin_id is not None else manifest.get("name"),
        plugin_version=manifest.get("version"),
        publisher=manifest.get("publisher"),
    )


def _recovery_result(deactivated: list[str], decision: Decision,
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
    log_item = item("captured service log for diagnosis", ok=ok, output=failure_log)
    result = {"plugin_id": SERVICES_PLUGIN_ID, "ok": ok, "skipped": False, "reason": reason,
              "failure_log": failure_log,
              "log": [phase("restart", "Restart services", [log_item])]}
    if deactivated:
        result["auto_deactivated"] = ", ".join(deactivated)
        result["fix_detail"] = decision.signal
    return result


def _auto_recover(plugin_root: Path, deferred_cmds: list[str], vars: dict[str, str],
                  ctx: OperationContext, evidence: FailureEvidence) -> dict:
    """Walk the fixer chain: deactivate the named culprit, restart, re-probe, repeat until the
    printer is healthy or no plugin is left to blame."""
    failure = evidence
    deactivated: list[str] = []
    decision = decide(evidence, ctx, deactivated)
    for _attempt in range(len(installed_manifest_dirs(plugin_root)) + 1):
        decision = decide(evidence, ctx, deactivated)
        if decision.culprit is None:
            break
        deactivate_plugin(plugin_root / decision.culprit, vars,
                          f"auto-deactivated: {decision.signal}")
        deactivated.append(decision.culprit)
        run_restart_batch(deferred_cmds)
        evidence = gather_evidence(plugin_root, vars)
        if is_healthy(evidence):
            break
    return _recovery_result(deactivated, decision, evidence, failure)


def _touches_core_service(deferred_cmds: list[str]) -> bool:
    """Only a core-service restart needs the safety net; a plugin-service or nginx bounce does not
    put the printer's base functions at risk, so we skip the probe + recovery for those. The jinni
    flags which commands restart a core service; the daemon never matches a command itself."""
    effects = jinni_client.classify_commands(deferred_cmds)
    return any(effect.restarts_services for effect in effects)


def restart_services(plugin_root: Path, deferred_cmds: list[str], vars: dict[str, str],
                     ctx: OperationContext) -> dict:
    """Do the restart, then ask the safety net to verify and recover. The daemon does the thing; the
    net watches (incl. failed components), acts (deactivate), and reports."""
    result = run_restart_batch(deferred_cmds)
    if not _touches_core_service(deferred_cmds):
        return result
    evidence = gather_evidence(plugin_root, vars)
    if is_healthy(evidence):
        return result
    return _auto_recover(plugin_root, deferred_cmds, vars, ctx, evidence)


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
