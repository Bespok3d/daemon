# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run the deferred core-service restarts once, then verify each restarted service came back up.

Restarts are deduped into one batch so a multi-plugin op bounces each service a single time. The
daemon asks the jinni to RUN the batch (executing a device command is the jinni's actuation, never
the daemon's); the jinni then reports the device health, and the daemon waits for each service it
restarted, named by the jinni and never indexed by a name the daemon authored. If one stayed down,
the config-link self-heal prunes stale include links and re-runs the restarts once more before
giving up.
"""
from protocol import ServiceHealth

from .. import jinni_client
from ..results import MAX_OUTPUT_BYTES, SERVICES_PLUGIN_ID, item, phase


def _run_items(commands: list[str]) -> list[dict]:
    """Ask the jinni to run the commands and turn each ActionResult into a phase item, keyed back to
    the command the daemon sent."""
    results = jinni_client.run_actions(commands)
    return [item(command, ok=result.ok, output=result.output)
            for command, result in zip(commands, results)]


_UNREPORTED = ServiceHealth(ready=False, detail="the printer did not report on this service")


def _health_of(reported: dict[str, ServiceHealth], name: str) -> ServiceHealth:
    """The verdict for one service the daemon just restarted. The health report is a second answer
    from the jinni and it may not list every service that was restarted; an unlisted one counts as
    not back up, so the safety net runs and takes the plugin out of the way, rather than failing on
    the lookup and leaving the printer with no safety net at all."""
    return reported.get(name, _UNREPORTED)


def _service_item(name: str, service: ServiceHealth) -> dict:
    return item(f"wait for {name} to come back up", ok=service.ready,
                output=service.detail[:MAX_OUTPUT_BYTES].strip())


def _restarted_service_names(deferred_cmds: list[str]) -> list[str]:
    effects = jinni_client.classify_commands(deferred_cmds)
    return sorted({name for effect in effects for name in effect.restarts_services})


def _verify_restarted(restarted: list[str], deferred_cmds: list[str]) -> tuple[list[dict], str]:
    """One wait item per restarted service from the jinni's health verdict, plus the jinni's log
    tail for diagnosis. If any service stayed down, prune dead bespok3d include links (junk from an
    earlier uninstall that breaks the include glob) and re-run the restarts EXACTLY ONCE more, then
    re-read. No second prune: a still-down service then has a cause outside our config, so stop."""
    device = jinni_client.health()
    items = [_service_item(name, _health_of(device.services, name)) for name in restarted]
    if all(_health_of(device.services, name).ready for name in restarted):
        return items, device.signals.log_tails
    removed = jinni_client.prune_dead_config_links()
    if not removed:
        return items, device.signals.log_tails
    jinni_client.run_actions(deferred_cmds)
    device = jinni_client.health()
    items = [item("removed dead config links", ok=True, output=", ".join(removed)),
             *(_service_item(name, _health_of(device.services, name)) for name in restarted)]
    return items, device.signals.log_tails


def run_restart_batch(deferred_cmds: list[str]) -> dict:
    """Run every deferred init-script restart once (deduped), then verify each restarted core
    service came back up. The daemon asks the jinni to run the batch and for the device's health,
    reads the verdict for each service it restarted, naming none itself; the user-facing log tail
    comes from the jinni's report, the daemon opens no device log."""
    items = _run_items(deferred_cmds)
    restarted = _restarted_service_names(deferred_cmds)
    log_tails = ""
    if restarted:
        verify_items, log_tails = _verify_restarted(restarted, deferred_cmds)
        items.extend(verify_items)
    if not all(entry["ok"] for entry in items):
        items.append(item("captured service log for diagnosis", ok=False, output=log_tails))
    restart_phase = phase("restart", "Restart services", items)
    reason = "" if restart_phase["ok"] else "a restarted service did not come back up"
    return {"plugin_id": SERVICES_PLUGIN_ID, "ok": restart_phase["ok"], "skipped": False,
            "reason": reason, "log": [restart_phase]}
