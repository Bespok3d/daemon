# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Drive the core.safety decision brain during a deferred core-service restart.

The safety net (core.safety) decides; this module acts: it runs the restart, gathers the evidence,
asks the brain who broke the printer, deactivates that plugin, and restarts again, surfacing the
outcome as install/reconfigure phases. A plugin left on while a plugin it needs is off is taken off
in the same round, from the dependency graph, so the printer does not fail on each one in turn.
This is what keeps a printer usable after an OTA firmware update: a plugin that breaks against the
new firmware peels itself off until a fixed version is published. It runs on every operation that
restarts a core service, not only recover.
"""

import logging
from pathlib import Path

from ... import jinni_client
from ...safety import (
    Decision,
    FailureEvidence,
    OperationContext,
    OperationKind,
    decide,
    is_healthy,
)
from ...safety.restart_batch import run_restart_batch
from ..deactivator import deactivate_with_dependents
from ..machinery import MACHINERY_PACKAGES, is_machinery
from ..manifest import installed_manifest_dirs
from ..switched_off_marker import safety_net_reason
from .evidence import gather_evidence
from .net_report import recovery_result, stranded_report, with_net_report
from .stranded import stranded_decision, switch_off_stranded

_log = logging.getLogger(__name__)


def op_context(kind: OperationKind, manifest: dict, plugin_id: str | None = None) -> OperationContext:  # noqa: E501
    """The operation the daemon is performing, for the safety net's report + last-resort blame."""
    return OperationContext(
        kind=kind,
        plugin_id=plugin_id if plugin_id is not None else manifest.get("name"),
        plugin_version=manifest.get("version"),
        publisher=manifest.get("publisher"),
    )


def _spared_from_blame(culprit: str, plugin_root: Path) -> bool:
    """Whether an automatic step must pass this culprit over instead of taking it off the printer.

    Two names are passed over: the printer's own machinery, which the owner would be left unable to
    reach the printer without, and a name that is not an installed plugin, which has nothing to
    undo and would otherwise leave a deactivation marker for something that was never there.
    """
    return is_machinery(culprit) or not (plugin_root / culprit / "manifest.json").exists()


def _blame(plugin_root: Path, evidence: FailureEvidence, ctx: OperationContext,
           handled: list[str]) -> Decision:
    """The next plugin to take off, a stranded one first: it cannot run, and the printer would
    otherwise fail on it one restart at a time."""
    decision = stranded_decision(plugin_root, handled) or decide(evidence, ctx, handled)
    if decision.culprit is None:
        _log.info("safety net: %s found nobody to blame (%s)", decision.fixer, decision.signal)
        return decision
    _log.info("safety net: %s blamed %s (%s)", decision.fixer, decision.culprit, decision.signal)
    return decision


def _auto_recover(plugin_root: Path, deferred_cmds: list[str], vars: dict[str, str],
                  ctx: OperationContext, evidence: FailureEvidence) -> dict:
    """Walk the fixer chain: deactivate the named culprit, whatever still needs it and every
    plugin that switch-off strands, restart, re-probe, repeat until the printer is healthy or no
    plugin is left to blame."""
    failure = evidence
    deactivated: list[str] = []
    spared: list[str] = []
    # The chain can name every installed plugin, plus the machinery, plus the operation's own target
    # when that is not installed. Each name is passed to the next round as handled, so this many
    # rounds is enough for every one of them and the loop cannot run on.
    rounds = len(installed_manifest_dirs(plugin_root)) + len(MACHINERY_PACKAGES) + 1
    for _attempt in range(rounds):
        handled = deactivated + spared
        decision = _blame(plugin_root, evidence, ctx, handled)
        if decision.culprit is None:
            break
        if _spared_from_blame(decision.culprit, plugin_root):
            _log.info("safety net: %s is spared, not deactivated", decision.culprit)
            spared.append(decision.culprit)
            continue
        reason = safety_net_reason(decision.signal, ctx.kind == OperationKind.RECOVER)
        deactivated.extend(deactivate_with_dependents(plugin_root, decision.culprit, vars, reason))
        deactivated.extend(switch_off_stranded(plugin_root, vars, ctx))
        run_restart_batch(deferred_cmds)
        evidence = gather_evidence(plugin_root, vars)
        if is_healthy(evidence):
            break
    return recovery_result(deactivated, decision, evidence, failure)


def touches_core_service(deferred_cmds: list[str]) -> bool:
    """Only a core-service restart needs the safety net; a plugin-service or nginx bounce does not
    put the printer's base functions at risk, so we skip the probe + recovery for those. The jinni
    flags which commands restart a core service; the daemon never matches a command itself."""
    effects = jinni_client.classify_commands(deferred_cmds)
    return any(effect.restarts_services for effect in effects)


def safety_net_check(plugin_root: Path, deferred_cmds: list[str], vars: dict[str, str],
                     ctx: OperationContext) -> dict | None:
    """Look at the printer once its services have restarted. Healthy is None; otherwise the net
    takes the culprit off, restarts with `deferred_cmds` and returns the recovery's row."""
    evidence = gather_evidence(plugin_root, vars)
    if is_healthy(evidence):
        _log.info("safety net: the printer is healthy")
        return None
    return _auto_recover(plugin_root, deferred_cmds, vars, ctx, evidence)


def restart_services(plugin_root: Path, deferred_cmds: list[str], vars: dict[str, str],
                     ctx: OperationContext) -> dict:
    """Do the restart, then ask the safety net to verify and recover. The daemon does the thing; the
    net watches (incl. failed components), acts (deactivate), and reports. A plugin left on while a
    plugin it needs is off is switched off before a core restart: the printer would fail on it, and
    finding that out costs a restart per plugin."""
    if not touches_core_service(deferred_cmds):
        return run_restart_batch(deferred_cmds)
    stranded = switch_off_stranded(plugin_root, vars, ctx)
    restart_row = stranded_report(run_restart_batch(deferred_cmds), stranded)
    net_row = safety_net_check(plugin_root, deferred_cmds, vars, ctx)
    return restart_row if net_row is None else with_net_report(restart_row, net_row)
