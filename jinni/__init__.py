"""The Jinni interface: the contract the generic daemon orders a target-specific adapter against.

The daemon owns everything inside the bespok3d filesystem and never knows a specific target. Every
adapter ships a Jinni (its daemon-side half), installed next to the daemon and loaded at runtime,
that REALIZES the host-crossing operations and reports the target's facts.

Three tiers:
- `Jinni` (this module): a generic linux box. It GUARANTEES the core path variables every device
  needs (`BESPOK3D`, `BESPOK3D_PLUGINS`, `RUNTIME_USER`) by construction, since `paths()` always
  merges them with whatever the device adds. It makes no klipper assumptions.
- `KlipperPrinterJinni`: a base for klipper-3d-printer adapters. It owns the klipper path-variable
  contract plus the klipper-only facts (klipper version, the moonraker probe, print state).
- the device jinni (shipped by the adapter) extends `KlipperPrinterJinni` and supplies only its own
  paths and hardware specifics.
"""
import json
import os
import socket
import subprocess
import urllib.request
from abc import ABC
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

_PROBE_HOST = "127.0.0.1"
_PORT_PROBE_TIMEOUT_S = 0.3
_PRINT_QUERY_TIMEOUT_S = 3
_KLIPPER_VERSION_TIMEOUT_S = 3
_HTTP_PORT = 80
_DAEMON_PORT = 4269
_MOONRAKER_PORT = 7125
_PRINTING_STATES = ("printing", "paused")

# Ports probed on ANY device, with the label shown to the user. A klipper printer jinni adds 7125.
_GENERIC_PORTS = {
    _HTTP_PORT: "Web UI",
    443: "Web UI (TLS)",
    1883: "MQTT",
    _DAEMON_PORT: "Bespok3d daemon",
}

# The path variables the bespok3d system itself needs on every device, whatever it is.
CORE_PATH_KEYS = frozenset({"BESPOK3D", "BESPOK3D_PLUGINS", "RUNTIME_USER"})

# The path variables a klipper printer adapter must expose (the VALUES are device-specific). The
# loader strict-output gate checks these are present for any KlipperPrinterJinni.
KLIPPER_PATH_KEYS = frozenset({
    "BESPOK3D_KLIPPER", "BESPOK3D_MOONRAKER", "KLIPPER_SRC", "KLIPPER_EXTRAS",
    "MOONRAKER_COMPONENTS", "PRINTER_CFG", "MOONRAKER_CFG",
})


def _plugin_endpoints(plugin_dir: Path) -> list[dict[str, str]]:
    manifest_path = plugin_dir / "manifest.json"
    if not manifest_path.exists():
        return []
    declared = json.loads(manifest_path.read_text()).get("endpoints", [])
    return [
        {"label": endpoint["label"], "url": f"http://{{host}}{endpoint['path']}"}
        for endpoint in declared
    ]


def endpoints_from_manifests(plugin_root: Path) -> list[dict[str, str]]:
    if not plugin_root.exists():
        return []
    result: list[dict[str, str]] = []
    for plugin_dir in plugin_root.iterdir():
        if plugin_dir.is_dir():
            result.extend(_plugin_endpoints(plugin_dir))
    return result


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(_PORT_PROBE_TIMEOUT_S)
        return probe.connect_ex((_PROBE_HOST, port)) == 0


def _print_state() -> tuple[bool, str]:
    url = f"http://{_PROBE_HOST}:{_MOONRAKER_PORT}/printer/objects/query?print_stats"
    try:
        with urllib.request.urlopen(url, timeout=_PRINT_QUERY_TIMEOUT_S) as response:
            payload = json.loads(response.read().decode(errors="replace"))
    except Exception:
        return False, ""
    stats = payload.get("result", {}).get("status", {}).get("print_stats", {})
    state = stats.get("state", "")
    return state in _PRINTING_STATES, state


def _endpoint_for(port: int) -> dict[str, str] | None:
    if port == _HTTP_PORT:
        return {"label": _GENERIC_PORTS[_HTTP_PORT], "url": "http://{host}"}
    if port == _MOONRAKER_PORT:
        return {"label": "Moonraker API", "url": "http://{host}:7125"}
    return None


def _root(url: str) -> str:
    return url.rstrip("/")


def _discovered_endpoints(open_ports: list[int], declared_roots: set[str]) -> list[dict[str, str]]:
    """Generic endpoints found by probing, minus any a plugin already serves at the same root.

    A specific plugin (fluidd, mainsail as primary) declaring the web root supersedes the generic
    "Web UI" entry, so the user sees the named UI rather than a duplicate generic link.
    """
    found: list[dict[str, str]] = []
    for port in open_ports:
        endpoint = _endpoint_for(port)
        if endpoint and _root(endpoint["url"]) not in declared_roots:
            found.append(endpoint)
    return found


class Jinni(ABC):
    id: str = "generic"

    def data_root(self) -> str:
        return os.environ.get("BESPOK3D_DATA_ROOT", "/opt/bespok3d")

    def runtime_user(self) -> str:
        return "root"

    def _core_paths(self) -> dict[str, str]:
        root = self.data_root()
        return {
            "BESPOK3D": root,
            "BESPOK3D_PLUGINS": f"{root}/usr/local/plugins",
            "RUNTIME_USER": self.runtime_user(),
        }

    def device_paths(self) -> dict[str, str]:
        """Variable -> host path mappings the device adds on top of the core set."""
        return {}

    def paths(self) -> dict[str, str]:
        return {**self._core_paths(), **self.device_paths()}

    def _plugin_root(self) -> Path:
        return Path(self.paths().get("BESPOK3D_PLUGINS", ""))

    def hardware(self) -> list[str]:
        return []

    def firmware_version(self) -> str:
        return "unknown"

    def version(self) -> str:
        """The adapter jinni's own version (its daemon-side half), distinct from the daemon."""
        return "unknown"

    def preferred_registries(self) -> list[str]:
        return []

    def capability_flags(self) -> set[str]:
        return set()

    def render_service_script(self, service: dict, paths: dict[str, str]) -> str:
        raise NotImplementedError("managed-service")

    def render_lmd_control_script(self, paths: dict[str, str]) -> str:
        """The hardened display-service control script, for adapters that flag `lmd-control`."""
        raise NotImplementedError("lmd-control")

    def background_tasks(self) -> list[Coroutine[Any, Any, None]]:
        return []

    def installed_plugins(self) -> dict[str, str]:
        plugin_root = self._plugin_root()
        if not plugin_root.is_dir():
            return {}
        installed: dict[str, str] = {}
        for plugin_dir in plugin_root.iterdir():
            manifest = plugin_dir / "manifest.json"
            if plugin_dir.is_dir() and manifest.exists():
                installed[plugin_dir.name] = json.loads(manifest.read_text()).get("version", "")
        return installed

    def deactivated_plugins(self) -> list[str]:
        """Installed plugins the safety net (or the user) turned off: their dir carries a
        deactivated.json marker. The app shows these as disabled, not installed-and-working."""
        plugin_root = self._plugin_root()
        if not plugin_root.is_dir():
            return []
        return sorted(
            plugin_dir.name for plugin_dir in plugin_root.iterdir()
            if (plugin_dir / "deactivated.json").exists()
        )

    def _candidate_ports(self) -> dict[int, str]:
        return dict(_GENERIC_PORTS)

    def _print_status(self) -> tuple[bool, str]:
        return False, ""

    def inspect(self) -> dict:
        declared = endpoints_from_manifests(self._plugin_root())
        declared_roots = {_root(endpoint["url"]) for endpoint in declared}
        open_ports = [port for port in sorted(self._candidate_ports()) if _port_open(port)]
        print_active, state = self._print_status()
        return {
            "open_ports": open_ports,
            "endpoints": declared + _discovered_endpoints(open_ports, declared_roots),
            "print_active": print_active,
            "state": state,
        }

    def diagnose(self) -> dict:
        return {"web": _port_open(_HTTP_PORT), "daemon": _port_open(_DAEMON_PORT)}

    def capabilities(self) -> dict:
        """The target facts the daemon relays. A custom jinni may extend this."""
        return {
            "adapter": self.id,
            "hardware": self.hardware(),
            "installed": self.installed_plugins(),
            "deactivated": self.deactivated_plugins(),
            "firmware_version": self.firmware_version(),
            "jinni_version": self.version(),
            "capability_flags": sorted(self.capability_flags()),
            "preferred_registries": self.preferred_registries(),
            "endpoints": self.inspect()["endpoints"],
        }


class KlipperPrinterJinni(Jinni):
    """Base for klipper-3d-printer adapters: the klipper path contract plus the klipper-only facts
    (klipper version, the moonraker probe, print state). A device adapter extends this and supplies
    only its own paths and hardware specifics.
    """

    KLIPPER_PATH_KEYS = KLIPPER_PATH_KEYS

    def _candidate_ports(self) -> dict[int, str]:
        return {**_GENERIC_PORTS, _MOONRAKER_PORT: "Moonraker API"}

    def _print_status(self) -> tuple[bool, str]:
        return _print_state()

    def diagnose(self) -> dict:
        return {**super().diagnose(), "moonraker": _port_open(_MOONRAKER_PORT)}

    def klipper_version(self) -> str:
        try:
            result = subprocess.run(
                ["python3", "-c", "import klippy; print(klippy.VERSION)"],
                capture_output=True, text=True, timeout=_KLIPPER_VERSION_TIMEOUT_S, check=False,
            )
            return result.stdout.strip() or "unknown"
        except Exception:
            return "unknown"

    def capabilities(self) -> dict:
        return {**super().capabilities(), "klipper_version": self.klipper_version()}


def interface_extras(jinni: Jinni) -> list[str]:
    """Public names a jinni exposes beyond the bespok3d jinni interface (the Jinni and
    KlipperPrinterJinni tiers). Computed by the DAEMON over the loaded object, not self-reported, so
    an adapter cannot hide the fact that it ships behaviour the daemon does not define. Non-empty is
    surfaced to the user as a caution.
    """
    defined = set(dir(Jinni)) | set(dir(KlipperPrinterJinni))
    return sorted(
        name for name in dir(type(jinni))
        if not name.startswith("_") and name not in defined
    )
