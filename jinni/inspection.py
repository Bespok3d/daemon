"""Generic device probes over loopback: low-level reachability, the endpoints plugins serve, and the
Klipper print state.

These are the readings the Jinni interface surfaces through `inspect()` and its reachability
methods. They talk to the device over loopback (a TCP connect, an HTTP query, Klipper's API socket)
and over the installed plugins' manifests; they name no concrete device, so they live in the generic
jinni layer. The base `Jinni` exposes `tcp_port_listening` / `http_service_get` as the overridable
`port_listening` / `service_get` methods, so a device with an unusual probe can replace them.
"""
import json
import socket
import urllib.error
import urllib.request
from pathlib import Path

from .printer_comms import klippy

_PROBE_HOST = "127.0.0.1"
_PORT_PROBE_TIMEOUT_S = 0.3
_PRINT_QUERY_TIMEOUT_S = 3

# Klipper / Moonraker answer these under `[authorization] force_logins` (the moonraker-auth plugin):
# the service IS up and answering, it just demands a login. A healthy, expected response, NOT a
# failure, so a reachability check must not read it as "down" (which auto-deactivated the plugin
# that set it).
_AUTH_REQUIRED_CODES = (401, 403)

HTTP_PORT = 80
DAEMON_PORT = 4269
MOONRAKER_PORT = 7125
MQTT_PORT = 1883

# Ports probed on ANY device, with the label shown to the user. A klipper printer jinni adds 7125.
GENERIC_PORTS = {
    HTTP_PORT: "Web UI",
    443: "Web UI (TLS)",
    MQTT_PORT: "MQTT",
    DAEMON_PORT: "Bespok3d daemon",
}


def tcp_port_listening(port: int) -> bool:
    """Whether a localhost TCP port is open (a connect probe)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(_PORT_PROBE_TIMEOUT_S)
        return probe.connect_ex((_PROBE_HOST, port)) == 0


def http_service_get(url: str, timeout: int = 3) -> tuple[bool, str]:
    """GET a localhost service URL, returning (up, body). An auth-required response still means the
    service is up; a connection error (refused / timeout) means it is not yet up."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return True, response.read().decode(errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code in _AUTH_REQUIRED_CODES:
            return True, f"auth required (HTTP {exc.code}); service is up"
        return False, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 - connection refused / timeout means not-yet-up
        return False, str(exc)


def print_state(socket_path: str) -> str:
    """Klipper's print_stats.state, read auth-immune over its API socket first (so it survives the
    moonraker-auth plugin's force_logins), falling back to Moonraker HTTP. "" when unread (which the
    caller reads as idle)."""
    state = klippy.query_print_state(socket_path) if socket_path else None
    return state if state is not None else _moonraker_print_state_http()


def _moonraker_print_state_http() -> str:
    url = f"http://{_PROBE_HOST}:{MOONRAKER_PORT}/printer/objects/query?print_stats"
    try:
        with urllib.request.urlopen(url, timeout=_PRINT_QUERY_TIMEOUT_S) as response:
            payload = json.loads(response.read().decode(errors="replace"))
    except Exception:  # noqa: BLE001 - unreachable / 401 under force_logins reads as idle
        return ""
    return str(payload.get("result", {}).get("status", {}).get("print_stats", {}).get("state", ""))


def _plugin_endpoints(plugin_dir: Path) -> list[dict[str, str]]:
    manifest_path = plugin_dir / "manifest.json"
    if not manifest_path.exists():
        return []
    declared = json.loads(manifest_path.read_text()).get("endpoints", [])
    return [
        {"label": endpoint["label"], "url": f"http://{{host}}{endpoint['path']}"}
        for endpoint in declared
    ]


def _endpoints_from_manifests(plugin_root: Path) -> list[dict[str, str]]:
    if not plugin_root.exists():
        return []
    result: list[dict[str, str]] = []
    for plugin_dir in plugin_root.iterdir():
        if plugin_dir.is_dir():
            result.extend(_plugin_endpoints(plugin_dir))
    return result


def _endpoint_for(port: int) -> dict[str, str] | None:
    if port == HTTP_PORT:
        return {"label": GENERIC_PORTS[HTTP_PORT], "url": "http://{host}"}
    if port == MOONRAKER_PORT:
        return {"label": "Moonraker API", "url": "http://{host}:7125"}
    return None


def _endpoint_root(url: str) -> str:
    return url.rstrip("/")


def _discovered_endpoints(open_ports: list[int], declared_roots: set[str]) -> list[dict[str, str]]:
    """Generic endpoints found by probing, minus any a plugin already serves at the same root.

    A specific plugin (fluidd, mainsail as primary) declaring the web root supersedes the generic
    "Web UI" entry, so the user sees the named UI rather than a duplicate generic link.
    """
    found: list[dict[str, str]] = []
    for port in open_ports:
        endpoint = _endpoint_for(port)
        if endpoint and _endpoint_root(endpoint["url"]) not in declared_roots:
            found.append(endpoint)
    return found


def visible_endpoints(plugin_root: Path, open_ports: list[int]) -> list[dict[str, str]]:
    """Endpoints visible on the device: those plugins declare, plus those discovered by probing
    (minus a generic entry a plugin already supersedes at the same root)."""
    declared = _endpoints_from_manifests(plugin_root)
    declared_roots = {_endpoint_root(endpoint["url"]) for endpoint in declared}
    return declared + _discovered_endpoints(open_ports, declared_roots)
