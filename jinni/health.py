"""The klipper printer's health verdict: one `DeviceHealth` report the daemon's safety net judges.

The daemon asks a single semantic question, "is the device healthy?", rather than probing each
service; `health()` assembles the report. Each service is read over its auth-free Unix socket
(`printer_comms`) so it survives the moonraker-auth plugin's force_logins, falling back to the
jinni's own reachability (an injected `service_get`); the stock MQTT broker is a device fact folded
in. The retry loops and the /server/info parsing live here as pure functions; the `KlipperHealth`
facet (also here) supplies the socket paths (from Layout) and the reachability probe (from Probing).
"""
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .contracts import KLIPPER_SERVICE, MOONRAKER_SERVICE, DeviceHealth, ServiceHealth
from .layout import Layout
from .printer_comms import klippy
from .printer_comms import moonraker as moonraker_client
from .probing import Probing


@dataclass
class MoonrakerInfo:
    """The health-relevant slice of Moonraker's /server/info, the jinni-internal parse `health()`
    folds into the moonraker `ServiceHealth`. `reachable` False means the read failed; a reachable
    Moonraker can still report `failed_components` (a component that imported badly)."""
    reachable: bool
    raw: str
    klippy_state: str = ""
    klippy_connected: bool = False
    failed_components: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

# A localhost reachability probe (the jinni's own service_get): (url) -> (up, body).
ServiceProbe = Callable[[str], tuple[bool, str]]

KLIPPER_RETRIES = 6
KLIPPER_RETRY_DELAY_S = 5
MOONRAKER_RETRIES = 60
MOONRAKER_RETRY_DELAY_S = 1

# Worst-case wall time health() spends retrying while a restarted service comes back (the sum of the
# inter-attempt sleeps across both probes). The daemon's seam sizes the health verb's socket timeout
# off this, so a legitimately slow restart (installing a plugin that bounces Moonraker) is never
# misread as "no reply from the jinni".
HEALTH_PROBE_BUDGET_S = (
    KLIPPER_RETRIES * KLIPPER_RETRY_DELAY_S + MOONRAKER_RETRIES * MOONRAKER_RETRY_DELAY_S
)

_KLIPPER_INFO_URL = "http://localhost:7125/printer/info"
_MOONRAKER_INFO_URL = "http://localhost:7125/server/info"


def _klipper_ready_once(socket_path: str, service_get: ServiceProbe) -> tuple[bool, str]:
    """One readiness check. Prefer Klipper's API socket (no auth, immune to Moonraker force_logins);
    fall back to the HTTP probe when the socket is unreachable."""
    state = klippy.query_klippy_state(socket_path) if socket_path else None
    if state is not None:
        return state == "ready", f"klippy state via api socket: {state or 'unknown'}"
    return service_get(_KLIPPER_INFO_URL)


def klipper_healthy(socket_path: str, service_get: ServiceProbe) -> tuple[bool, str]:
    last_out = ""
    for attempt in range(KLIPPER_RETRIES):
        ok, out = _klipper_ready_once(socket_path, service_get)
        if ok:
            return True, out
        last_out = out
        if attempt < KLIPPER_RETRIES - 1:
            time.sleep(KLIPPER_RETRY_DELAY_S)
    return False, last_out


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


def _probe_moonraker_once(socket_path: str, service_get: ServiceProbe) -> MoonrakerInfo:
    """One probe. Prefer Moonraker's auth-free Unix socket so failed_components/warnings survive
    force_logins; fall back to HTTP /server/info (a 401 there still means up, body unreadable)."""
    result = moonraker_client.server_info(socket_path) if socket_path else None
    if result is not None:
        return _info_from_result(result, json.dumps(result))
    up, body = service_get(_MOONRAKER_INFO_URL)
    return _parse_server_info(body) if up else MoonrakerInfo(reachable=False, raw=body)


def probe_moonraker(socket_path: str, service_get: ServiceProbe) -> MoonrakerInfo:
    """Reach Moonraker and read failed components, retrying while unreachable."""
    last_out = ""
    for attempt in range(MOONRAKER_RETRIES):
        info = _probe_moonraker_once(socket_path, service_get)
        if info.reachable:
            return info
        last_out = info.raw
        if attempt < MOONRAKER_RETRIES - 1:
            time.sleep(MOONRAKER_RETRY_DELAY_S)
    return MoonrakerInfo(reachable=False, raw=last_out)


class KlipperHealth(Layout, Probing):
    """The health facet for a klipper printer: assemble the `DeviceHealth` report by probing Klipper
    and Moonraker over their auth-free sockets (HTTP fallback). It reports the domain services only;
    a device's own infrastructure (the U1's stock MQTT broker) is the device jinni's to diagnose.
    Inherits Layout (socket paths) and Probing (the reachability probe)."""

    def health(self) -> DeviceHealth:
        paths = self.paths()
        klipper_ready, klipper_detail = klipper_healthy(paths.get("KLIPPER_UDS", ""), self.service_get)  # noqa: E501
        moonraker = probe_moonraker(paths.get("MOONRAKER_UDS", ""), self.service_get)
        return DeviceHealth(
            services={
                KLIPPER_SERVICE: ServiceHealth(ready=klipper_ready, detail=klipper_detail),
                MOONRAKER_SERVICE: ServiceHealth(
                    ready=moonraker.reachable, detail=moonraker.raw,
                    failed_components=tuple(moonraker.failed_components),
                    warnings=tuple(moonraker.warnings),
                ),
            },
        )
