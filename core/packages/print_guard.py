"""Print-safety guards: refuse a plugin op that would restart a service mid-print.

Every guard makes a LIVE check at the moment of the op (Klipper's auth-immune API socket first,
Moonraker HTTP as a fallback), never a cached or periodic value.
"""

import json
import urllib.request
from pathlib import Path

from ..intent import normalize_install
from ..printer_comms.klippy import query_print_state
from ..safety.health import klippy_socket_path
from ..service_actions import restarts_klipper, restarts_lmd, restarts_moonraker

_PRINTING_STATES = ("printing", "paused")


def _print_state_via_moonraker() -> str:
    """Fallback when Klipper's API socket is unavailable. Returns "" on any failure (including a 401
    under force_logins), which reads as idle: the auth-immune Klipper socket is the main source."""
    try:
        url = "http://localhost:7125/printer/objects/query?print_stats"
        with urllib.request.urlopen(url, timeout=3) as resp:
            payload = json.loads(resp.read().decode(errors="replace"))
    except Exception:
        return ""
    return str(payload.get("result", {}).get("status", {}).get("print_stats", {}).get("state", ""))


def _print_active() -> tuple[bool, str]:
    """Return (is_active, state). Reads Klipper's print_stats over its API socket (no auth, so it
    works even when the moonraker-auth plugin forces logins); falls back to Moonraker HTTP when the
    socket is unavailable. An idle / unreadable result is treated as not-printing."""
    socket_path = klippy_socket_path()
    state = query_print_state(socket_path) if socket_path else None
    if state is None:
        state = _print_state_via_moonraker()
    return state in _PRINTING_STATES, state


def _manifest_restarts_services(manifest: dict) -> bool:
    ops = normalize_install(manifest.get("install", {}))
    start_cmds = ops["start"]
    if any(restarts_klipper(cmd) or restarts_moonraker(cmd) for cmd in start_cmds):
        return True
    # A plugin that bounces the display service (lmd) is detectable two ways: the generic
    # `restart: ["lmd"]` hook lands an `lmdctl` command in `start`, and a display-owning plugin
    # like camera-hw-accel (whose start runs its own init script with no literal "lmd") declares
    # `lmdctl restart` in its teardown `stop`. Either marks it as display-touching.
    display_cmds = [*start_cmds, *ops["stops"], *manifest.get("stop", [])]
    return any(restarts_lmd(cmd) for cmd in display_cmds)


def guard_no_print(action: str) -> None:
    """Refuse a system-wide plugin op (deactivate/teardown/recover) while printing or paused.

    These bounce services across all plugins, so the check is unconditional: a LIVE Moonraker
    query at the moment of the op, never a cached/periodic value.
    """
    active, state = _print_active()
    if active:
        raise ValueError(
            f"Cannot {action} while a print is {state}: it restarts printer services, which "
            "would interrupt the print. Try again when the printer is idle."
        )


def guard_no_print_during_restart(manifest: dict, action: str = "install") -> None:
    """Refuse an op that would bounce Klipper, Moonraker, or the display while printing/paused."""
    if not _manifest_restarts_services(manifest):
        return
    active, state = _print_active()
    if not active:
        return
    raise ValueError(
        f"Cannot {action} {manifest.get('name', 'this plugin')} while a print is {state}: "
        "it restarts Klipper, Moonraker, or the display service, which would interrupt the "
        "print. Try again when the printer is idle."
    )


def guard_batch_no_print(manifests: list[dict]) -> None:
    """Refuse the whole batch up front if any update restarts Klipper/Moonraker mid-print."""
    if not any(_manifest_restarts_services(manifest) for manifest in manifests):
        return
    active, state = _print_active()
    if not active:
        return
    raise ValueError(
        f"Cannot update plugins while a print is {state}: some updates restart Klipper or "
        "Moonraker, which would interrupt the print. Try again when the printer is idle."
    )


def guard_no_print_for_removal(plugin_root: Path, plugin_ids: list[str]) -> None:
    """Refuse removing any plugin that would bounce a core/display service while printing/paused."""
    for plugin_id in plugin_ids:
        manifest_path = plugin_root / plugin_id / "manifest.json"
        if manifest_path.exists():
            guard_no_print_during_restart(json.loads(manifest_path.read_text()), action="remove")
