"""Run the deferred core-service restarts once, then verify Klipper and Moonraker came back up.

Restarts are deduped into one batch so a multi-plugin op bounces each service a single time. After
running them, wait for whichever service was restarted to answer; if Moonraker stays down, the
config-link self-heal prunes stale include links and restarts it one more time before giving up.
"""
from ..results import MAX_OUTPUT_BYTES, item, phase
from ..service_actions import restarts_klipper, restarts_moonraker
from ..shell import run_one_command, start_env
from .config_links import prune_dead_config_links, restart_moonraker
from .logs import service_log_tails
from .probe.klipper import klipper_healthy
from .probe.moonraker import moonraker_healthy


def _wait_for_moonraker_item() -> dict:
    """Wait for Moonraker after a restart. If it stays down, prune stale include links and restart
    it EXACTLY ONCE more, then wait again. No recursion and no second prune: if it is still down
    after that single self-heal, the cause is outside our config so we stop."""
    healthy, out = moonraker_healthy()
    removed = [] if healthy else prune_dead_config_links()
    if removed:
        restart_moonraker()
        healthy, out = moonraker_healthy()
    detail = out[:MAX_OUTPUT_BYTES].strip()
    if removed:
        detail = "Removed dead config links: " + ", ".join(removed) + "\n" + detail
    return item("wait for moonraker to come back up", ok=healthy, output=detail)


def _wait_for_klipper_item() -> dict:
    healthy, out = klipper_healthy()
    detail = out[:MAX_OUTPUT_BYTES].strip()
    return item("wait for klipper to come back up", ok=healthy, output=detail)


def run_restart_batch(deferred_cmds: list[str], vars: dict[str, str]) -> dict:
    """Run every deferred init-script restart once (deduped), then wait for Klipper + Moonraker."""
    env = start_env()
    items = [run_one_command(cmd, env) for cmd in deferred_cmds]
    if any(restarts_moonraker(cmd) for cmd in deferred_cmds):
        items.append(_wait_for_moonraker_item())
    if any(restarts_klipper(cmd) for cmd in deferred_cmds):
        items.append(_wait_for_klipper_item())
    if not all(entry["ok"] for entry in items):
        items.append(item("captured service log for diagnosis", ok=False, output=service_log_tails(vars)))  # noqa: E501
    restart_phase = phase("restart", "Restart services", items)
    reason = "" if restart_phase["ok"] else "Klipper or Moonraker did not come back up"
    return {"plugin_id": "(services)", "ok": restart_phase["ok"], "skipped": False,
            "reason": reason, "log": [restart_phase]}
