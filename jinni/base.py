"""The base Jinni tier: a generic linux box.

It GUARANTEES the core path variables every device needs (`BESPOK3D`, `BESPOK3D_PLUGINS`,
`RUNTIME_USER`) by construction, since `paths()` always merges them with whatever the device adds.
It makes no klipper assumptions; the klipper tier (`jinni/klipper.py`) adds those, and the device
jinni (shipped by the adapter) supplies the concrete paths and hardware specifics.
"""
import json
import os
from abc import ABC
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

from . import inspection
from .contracts import ControlScript, ServiceActionVocabulary

# The path variables the bespok3d system itself needs on every device, whatever it is.
CORE_PATH_KEYS = frozenset({"BESPOK3D", "BESPOK3D_PLUGINS", "RUNTIME_USER"})

# Placement classes the bespok3d layout owns directly (over the daemon's own $BESPOK3D tree). They
# resolve to a $VAR-templated path the executor expands; the value names no concrete device. Klipper
# placement classes live on the klipper tier (jinni/klipper.py).
_BESPOK3D_PLACEMENTS = {
    "system-bin": "$BESPOK3D/bin/{name}",
    "web-location": "$BESPOK3D/etc/nginx/locations/{name}",
}


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

    def placement_destination(self, destination_class: str, name: str) -> str:
        """The $VAR-templated path a placed file of `destination_class` lands at. The base tier owns
        the bespok3d-layout classes; a printer tier adds its own and defers to super() for these."""
        template = _BESPOK3D_PLACEMENTS.get(destination_class)
        if template is None:
            raise ValueError(f"unsupported destination class: {destination_class}")
        return template.format(name=name)

    def instrument_destination(self, instrument_class: str, name: str) -> str:
        """The $VAR-templated path an instrumentation diff patches. The base tier instruments
        nothing; a printer tier adds its source classes and defers to super() for the unknown."""
        raise ValueError(f"unsupported instrument class: {instrument_class}")

    def restart_command(self, hook: str) -> str | None:
        """The shell command that restarts the core service named by `hook` (klipper, moonraker,
        web, lmd), or None when the device has no such service. The commands are genuine device
        facts, so the base tier knows none; a device jinni supplies them."""
        return None

    def service_action_vocabulary(self) -> ServiceActionVocabulary:
        """The device tokens the service-action classifier uses to spot a display or core-service
        command. The base tier names none; a device jinni supplies its own."""
        return ServiceActionVocabulary()

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

    def startup_control_scripts(self, paths: dict[str, str]) -> list[ControlScript]:
        """Control scripts the daemon writes into the persistent bespok3d tree on startup (e.g. a
        display control script). The base tier declares none; a device jinni returns its own."""
        return []

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
        return dict(inspection.GENERIC_PORTS)

    def _print_status(self) -> tuple[bool, str]:
        return False, ""

    def inspect(self) -> dict:
        open_ports = [
            port for port in sorted(self._candidate_ports()) if inspection.port_open(port)
        ]
        print_active, state = self._print_status()
        return {
            "open_ports": open_ports,
            "endpoints": inspection.visible_endpoints(self._plugin_root(), open_ports),
            "print_active": print_active,
            "state": state,
        }

    def diagnose(self) -> dict:
        return {
            "web": inspection.port_open(inspection.HTTP_PORT),
            "daemon": inspection.port_open(inspection.DAEMON_PORT),
        }

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
