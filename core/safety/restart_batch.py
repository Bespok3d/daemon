"""Run the deferred core-service restarts once, then verify Klipper and Moonraker came back up.

Restarts are deduped into one batch so a multi-plugin op bounces each service a single time. After
running them, wait for whichever service was restarted to answer; if Moonraker stays down, the
config-link self-heal prunes stale include links and restarts it one more time before giving up.
"""
from jinni.contracts import KLIPPER_SERVICE, MOONRAKER_SERVICE, ServiceHealth

from .. import jinni_client
from ..results import MAX_OUTPUT_BYTES, item, phase
from ..shell import run_one_command, start_env
from .config_links import prune_dead_config_links, restart_moonraker
from .logs import service_log_tails


def _detail(service: ServiceHealth) -> str:
    return service.detail[:MAX_OUTPUT_BYTES].strip()


def _moonraker_item(moonraker: ServiceHealth) -> dict:
    """Verdict for Moonraker after a restart. If it stayed down, prune stale include links and
    restart it EXACTLY ONCE more, then re-read. No second prune: if it is still down after that
    single self-heal, the cause is outside our config so we stop."""
    removed = [] if moonraker.ready else prune_dead_config_links()
    if removed:
        restart_moonraker()
        moonraker = jinni_client.health().services[MOONRAKER_SERVICE]
    detail = _detail(moonraker)
    if removed:
        detail = "Removed dead config links: " + ", ".join(removed) + "\n" + detail
    return item("wait for moonraker to come back up", ok=moonraker.ready, output=detail)


def _klipper_item(klipper: ServiceHealth) -> dict:
    return item("wait for klipper to come back up", ok=klipper.ready, output=_detail(klipper))


def run_restart_batch(deferred_cmds: list[str], vars: dict[str, str]) -> dict:
    """Run every deferred init-script restart once (deduped), then wait for Klipper + Moonraker. The
    daemon asks the jinni once for the device's health and reads the verdict for each service it
    restarted."""
    env = start_env()
    items = [run_one_command(cmd, env) for cmd in deferred_cmds]
    effects = jinni_client.classify_commands(deferred_cmds)
    wants_moonraker = any(effect.restarts_moonraker for effect in effects)
    wants_klipper = any(effect.restarts_klipper for effect in effects)
    if wants_moonraker or wants_klipper:
        device = jinni_client.health()
        if wants_moonraker:
            items.append(_moonraker_item(device.services[MOONRAKER_SERVICE]))
        if wants_klipper:
            items.append(_klipper_item(device.services[KLIPPER_SERVICE]))
    if not all(entry["ok"] for entry in items):
        items.append(item("captured service log for diagnosis", ok=False, output=service_log_tails(vars)))  # noqa: E501
    restart_phase = phase("restart", "Restart services", items)
    reason = "" if restart_phase["ok"] else "Klipper or Moonraker did not come back up"
    return {"plugin_id": "(services)", "ok": restart_phase["ok"], "skipped": False,
            "reason": reason, "log": [restart_phase]}
