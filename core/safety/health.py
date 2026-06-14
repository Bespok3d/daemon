"""Probe whether Klipper and Moonraker are actually usable, and run the deferred restart batch.

The subtle part lives here: Moonraker degrades gracefully. A component that fails to import (e.g.
the stock `notifier` doing `import apprise` with apprise absent) is recorded in `/server/info`'s
`failed_components` + `warnings` while the server keeps answering. So "reachable" is NOT "healthy" -
`parse_server_info` exposes the failed components so the safety net can judge real health.
"""
import json
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from jinni.loader import get_jinni

from ..intent import RESTART_HOOKS, restarts_klipper, restarts_moonraker
from ..printer_comms import klippy, moonraker
from ..results import MAX_OUTPUT_BYTES, item, phase
from ..shell import run_one_command, start_env
from .logs import service_log_tails

MOONRAKER_RETRIES = 60
MOONRAKER_RETRY_DELAY_S = 1
KLIPPER_RETRIES = 6
KLIPPER_RETRY_DELAY_S = 5
MQTT_PORT = 1883

_MOONRAKER_INFO_URL = "http://localhost:7125/server/info"
_KLIPPER_INFO_URL = "http://localhost:7125/printer/info"

# Moonraker returns these when `[authorization] force_logins` is on (the moonraker-auth plugin): the
# server IS up and answering, it just demands a login. That is a healthy, expected response, NOT a
# failure, so health probes must not read it as "down" (which auto-deactivated the plugin that set
# it).
_AUTH_REQUIRED_CODES = (401, 403)


def _service_get(url: str, timeout: int = 3) -> tuple[bool, str]:
    """GET a localhost service URL. Returns (up, body). An auth-required response still means the
    service is up; a connection error (refused / timeout) means it is not yet up."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return True, resp.read().decode(errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code in _AUTH_REQUIRED_CODES:
            return True, f"auth required (HTTP {exc.code}); service is up"
        return False, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 - connection refused / timeout means not-yet-up
        return False, str(exc)


@dataclass
class MoonrakerInfo:
    """The health-relevant slice of /server/info. `reachable` False means the HTTP call failed."""
    reachable: bool
    raw: str
    klippy_state: str = ""
    klippy_connected: bool = False
    failed_components: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _info_from_result(result: dict, raw: str) -> MoonrakerInfo:
    return MoonrakerInfo(
        reachable=True,
        raw=raw,
        klippy_state=str(result.get("klippy_state", "")),
        klippy_connected=bool(result.get("klippy_connected", False)),
        failed_components=list(result.get("failed_components", []) or []),
        warnings=list(result.get("warnings", []) or []),
    )


def parse_server_info(body: str) -> MoonrakerInfo:
    try:
        result = json.loads(body).get("result", {})
    except (ValueError, AttributeError):
        return MoonrakerInfo(reachable=True, raw=body)
    return _info_from_result(result, body)


def moonraker_socket_path() -> str:
    """Moonraker's Unix socket (comms/moonraker.sock), from the adapter's paths. Empty off-device or
    when undeclared, so callers fall back to the HTTP probe."""
    try:
        return get_jinni().paths().get("MOONRAKER_UDS", "")
    except Exception:  # noqa: BLE001 - no jinni on a non-printer host
        return ""


def _probe_moonraker_once(socket_path: str) -> MoonrakerInfo:
    """One probe. Prefer Moonraker's auth-free Unix socket so failed_components/warnings survive
    force_logins; fall back to HTTP /server/info (a 401 there still means up, body unreadable)."""
    if socket_path:
        result = moonraker.server_info(socket_path)
        if result is not None:
            return _info_from_result(result, json.dumps(result)[:MAX_OUTPUT_BYTES])
    up, body = _service_get(_MOONRAKER_INFO_URL)
    return parse_server_info(body) if up else MoonrakerInfo(reachable=False, raw=body)


def probe_moonraker() -> MoonrakerInfo:
    """Reach Moonraker and read failed components, retrying while unreachable. Uses Moonraker's own
    Unix socket first (no auth) so introspection survives the moonraker-auth plugin's force_logins;
    the auth-tolerant HTTP probe is the fallback."""
    socket_path = moonraker_socket_path()
    last_out = ""
    for attempt in range(MOONRAKER_RETRIES):
        info = _probe_moonraker_once(socket_path)
        if info.reachable:
            return info
        last_out = info.raw
        if attempt < MOONRAKER_RETRIES - 1:
            time.sleep(MOONRAKER_RETRY_DELAY_S)
    return MoonrakerInfo(reachable=False, raw=last_out)


def moonraker_healthy() -> tuple[bool, str]:
    """Reachability only (used by the dead-link self-heal). The richer verdict that also rejects
    failed components is made by the safety net against `probe_moonraker()`."""
    info = probe_moonraker()
    return info.reachable, info.raw


def klippy_socket_path() -> str:
    """The Klipper API server's Unix socket, from the adapter's paths. Empty off-device (no jinni),
    or when the adapter does not declare it, so callers fall back to the HTTP probe."""
    try:
        return get_jinni().paths().get("KLIPPER_UDS", "")
    except Exception:  # noqa: BLE001 - no jinni on a non-printer host
        return ""


def _klipper_ready_once(socket_path: str) -> tuple[bool, str]:
    """One readiness check. Prefer Klipper's API socket (no auth, immune to Moonraker force_logins);
    fall back to the Moonraker HTTP probe when the socket is unreachable."""
    if socket_path:
        state = klippy.query_klippy_state(socket_path)
        if state is not None:
            return state == "ready", f"klippy state via api socket: {state or 'unknown'}"
    return _service_get(_KLIPPER_INFO_URL)


def klipper_healthy() -> tuple[bool, str]:
    socket_path = klippy_socket_path()
    last_out = ""
    for attempt in range(KLIPPER_RETRIES):
        ok, out = _klipper_ready_once(socket_path)
        if ok:
            return True, out
        last_out = out
        if attempt < KLIPPER_RETRIES - 1:
            time.sleep(KLIPPER_RETRY_DELAY_S)
    return False, last_out


def config_link_dirs() -> list[Path]:
    """The bespok3d include dirs where plugin .cfg symlinks live (config/bespok3d/*)."""
    try:
        paths = get_jinni().paths()
    except Exception:  # noqa: BLE001 - missing jinni on a non-printer host: nothing to prune
        return []
    keys = ("BESPOK3D_KLIPPER", "BESPOK3D_MOONRAKER")
    return [Path(paths[key]) for key in keys if paths.get(key)]


def prune_dead_config_links(dirs: list[Path] | None = None) -> list[str]:
    """Remove symlinks under the bespok3d include dirs whose target no longer exists. A dead include
    link makes Klipper/Moonraker fail to start and is always junk left from an earlier uninstall, so
    removing it is safe. Returns the paths removed. `dirs` is injectable for tests."""
    removed: list[str] = []
    for directory in config_link_dirs() if dirs is None else dirs:
        if not directory.is_dir():
            continue
        for entry in sorted(directory.iterdir()):
            if entry.is_symlink() and not entry.exists():
                entry.unlink()
                removed.append(str(entry))
    return removed


def restart_moonraker() -> None:
    subprocess.run(
        RESTART_HOOKS["moonraker"], shell=True, capture_output=True, check=False, env=start_env()
    )


def wait_for_moonraker_item() -> dict:
    """Wait for Moonraker after a restart. If it stays down, prune stale include links and restart
    it EXACTLY ONCE more, then wait again. No recursion and no second prune: if it is still down
    after that single self-heal, the cause is outside our config so we stop."""
    healthy, out = moonraker_healthy()
    removed: list[str] = []
    if not healthy:
        removed = prune_dead_config_links()
        if removed:
            restart_moonraker()
            healthy, out = moonraker_healthy()
    detail = out[:MAX_OUTPUT_BYTES].strip()
    if removed:
        detail = "Removed dead config links: " + ", ".join(removed) + "\n" + detail
    return item("wait for moonraker to come back up", ok=healthy, output=detail)


def wait_for_klipper_item() -> dict:
    healthy, out = klipper_healthy()
    detail = out[:MAX_OUTPUT_BYTES].strip()
    return item("wait for klipper to come back up", ok=healthy, output=detail)


def run_restart_batch(deferred_cmds: list[str], vars: dict[str, str]) -> dict:
    """Run every deferred init-script restart once (deduped), then wait for Klipper + Moonraker."""
    env = start_env()
    items = [run_one_command(cmd, env) for cmd in deferred_cmds]
    if any(restarts_moonraker(cmd) for cmd in deferred_cmds):
        items.append(wait_for_moonraker_item())
    if any(restarts_klipper(cmd) for cmd in deferred_cmds):
        items.append(wait_for_klipper_item())
    if not all(entry["ok"] for entry in items):
        items.append(item("captured service log for diagnosis", ok=False, output=service_log_tails(vars)))  # noqa: E501
    restart_phase = phase("restart", "Restart services", items)
    reason = "" if restart_phase["ok"] else "Klipper or Moonraker did not come back up"
    return {"plugin_id": "(services)", "ok": restart_phase["ok"], "skipped": False,
            "reason": reason, "log": [restart_phase]}


def port_listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.3)
        return probe.connect_ex(("127.0.0.1", port)) == 0
