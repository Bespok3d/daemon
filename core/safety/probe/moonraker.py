"""Probe whether Moonraker is usable, reading the failed components it reports.

The subtle part: Moonraker degrades gracefully. A component that fails to import (e.g. the stock
`notifier` doing `import apprise` with apprise absent) is recorded in `/server/info`'s
`failed_components` + `warnings` while the server keeps answering. So "reachable" is NOT "healthy" -
the parsed info exposes the failed components so the safety net can judge real health.
"""
import json
import time
from dataclasses import dataclass, field

from jinni.loader import get_jinni

from ...printer_comms import moonraker as moonraker_client
from ...results import MAX_OUTPUT_BYTES
from .reach import service_get

MOONRAKER_RETRIES = 60
MOONRAKER_RETRY_DELAY_S = 1

_MOONRAKER_INFO_URL = "http://localhost:7125/server/info"


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


def _parse_server_info(body: str) -> MoonrakerInfo:
    try:
        result = json.loads(body).get("result", {})
    except (ValueError, AttributeError):
        return MoonrakerInfo(reachable=True, raw=body)
    return _info_from_result(result, body)


def _moonraker_socket_path() -> str:
    """Moonraker's Unix socket (comms/moonraker.sock), from the adapter's paths. Empty off-device or
    when undeclared, so callers fall back to the HTTP probe."""
    try:
        return get_jinni().paths().get("MOONRAKER_UDS", "")
    except Exception:  # noqa: BLE001 - no jinni on a non-printer host
        return ""


def _probe_moonraker_once(socket_path: str) -> MoonrakerInfo:
    """One probe. Prefer Moonraker's auth-free Unix socket so failed_components/warnings survive
    force_logins; fall back to HTTP /server/info (a 401 there still means up, body unreadable)."""
    result = moonraker_client.server_info(socket_path) if socket_path else None
    if result is not None:
        return _info_from_result(result, json.dumps(result)[:MAX_OUTPUT_BYTES])
    up, body = service_get(_MOONRAKER_INFO_URL)
    return _parse_server_info(body) if up else MoonrakerInfo(reachable=False, raw=body)


def probe_moonraker() -> MoonrakerInfo:
    """Reach Moonraker and read failed components, retrying while unreachable. Uses Moonraker's own
    Unix socket first (no auth) so introspection survives the moonraker-auth plugin's force_logins;
    the auth-tolerant HTTP probe is the fallback."""
    socket_path = _moonraker_socket_path()
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
