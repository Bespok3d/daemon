"""Probing a device for what is reachable: open ports, the endpoints plugins serve, and print state.

These are the generic readings the Jinni interface surfaces through `inspect()` and `diagnose()`.
They talk to the device over loopback (a TCP connect, a Moonraker HTTP query) and over the installed
plugins' manifests; they name no concrete device, so they belong in the generic jinni layer.
"""
import json
import socket
import urllib.request
from pathlib import Path

_PROBE_HOST = "127.0.0.1"
_PORT_PROBE_TIMEOUT_S = 0.3
_PRINT_QUERY_TIMEOUT_S = 3
_PRINTING_STATES = ("printing", "paused")

HTTP_PORT = 80
DAEMON_PORT = 4269
MOONRAKER_PORT = 7125

# Ports probed on ANY device, with the label shown to the user. A klipper printer jinni adds 7125.
GENERIC_PORTS = {
    HTTP_PORT: "Web UI",
    443: "Web UI (TLS)",
    1883: "MQTT",
    DAEMON_PORT: "Bespok3d daemon",
}


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(_PORT_PROBE_TIMEOUT_S)
        return probe.connect_ex((_PROBE_HOST, port)) == 0


def moonraker_print_state() -> tuple[bool, str]:
    url = f"http://{_PROBE_HOST}:{MOONRAKER_PORT}/printer/objects/query?print_stats"
    try:
        with urllib.request.urlopen(url, timeout=_PRINT_QUERY_TIMEOUT_S) as response:
            payload = json.loads(response.read().decode(errors="replace"))
    except Exception:
        return False, ""
    stats = payload.get("result", {}).get("status", {}).get("print_stats", {})
    state = stats.get("state", "")
    return state in _PRINTING_STATES, state


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
