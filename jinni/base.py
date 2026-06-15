"""The base Jinni tier: a generic linux box, composed from the concern facets.

The jinni interface spans four concerns, one facet module each: the filesystem `layout` contract,
the install-intent `realization` (placement / restart / service scripts), the reported target
`facts`, and the live `probing` (reachability, print state, the permission gate). This tier wires
them together (so the daemon talks to one flat object), guarantees the core path variables by
construction, and assembles the reports the daemon relays. It makes no klipper assumptions; the
klipper tier (`jinni/klipper.py`) overrides the facets that talk to Klipper/Moonraker.
"""
from abc import ABC

from . import inspection, installed
from .contracts import DeviceHealth
from .facts import Facts
from .layout import Layout
from .probing import Probing
from .realization import Realization


class Jinni(Layout, Realization, Facts, Probing, ABC):
    id: str = "generic"

    def installed_plugins(self) -> dict[str, str]:
        return installed.list_installed(self._plugin_root())

    def deactivated_plugins(self) -> list[str]:
        return installed.list_deactivated(self._plugin_root())

    def inspect(self) -> dict:
        open_ports = [
            port for port in sorted(self._candidate_ports()) if self.port_listening(port)
        ]
        active, state = self.print_active()
        return {
            "open_ports": open_ports,
            "endpoints": inspection.visible_endpoints(self._plugin_root(), open_ports),
            "print_active": active,
            "state": state,
        }

    def diagnose(self) -> dict:
        return {
            "web": self.port_listening(inspection.HTTP_PORT),
            "daemon": self.port_listening(inspection.DAEMON_PORT),
        }

    def health(self) -> DeviceHealth:
        """A generic box declares no critical services, so it is vacuously healthy; a printer tier
        overrides this to probe its real services. The daemon asks the loaded jinni for the verdict
        without knowing which tier answered, so the seam never narrows to a klipper printer."""
        return DeviceHealth(services={})

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
