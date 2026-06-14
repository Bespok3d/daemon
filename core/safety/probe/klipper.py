"""Probe whether Klipper is ready, preferring its auth-free API socket."""
import time

from jinni.loader import get_jinni

from ...printer_comms import klippy
from .reach import service_get

KLIPPER_RETRIES = 6
KLIPPER_RETRY_DELAY_S = 5

_KLIPPER_INFO_URL = "http://localhost:7125/printer/info"


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
    state = klippy.query_klippy_state(socket_path) if socket_path else None
    if state is not None:
        return state == "ready", f"klippy state via api socket: {state or 'unknown'}"
    return service_get(_KLIPPER_INFO_URL)


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
