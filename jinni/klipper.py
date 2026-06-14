"""The klipper-printer Jinni tier: a base for klipper-3d-printer adapters.

It owns the klipper path-variable contract plus the klipper-only facts (klipper version, the
moonraker probe, print state). A device adapter extends this and supplies only its own paths and
hardware specifics.
"""
import subprocess

from . import inspection
from .base import Jinni

_KLIPPER_VERSION_TIMEOUT_S = 3

# The path variables a klipper printer adapter must expose (the VALUES are device-specific). The
# loader strict-output gate checks these are present for any KlipperPrinterJinni.
KLIPPER_PATH_KEYS = frozenset({
    "BESPOK3D_KLIPPER", "BESPOK3D_MOONRAKER", "KLIPPER_SRC", "KLIPPER_EXTRAS",
    "MOONRAKER_COMPONENTS", "PRINTER_CFG", "MOONRAKER_CFG",
})

# Placement and instrument classes a klipper printer adds, resolving to $VAR-templated paths over
# the klipper path contract above. The executor expands the variables from the device jinni's paths.
_KLIPPER_PLACEMENTS = {
    "klipper-config": "$BESPOK3D_KLIPPER/{name}",
    "moonraker-config": "$BESPOK3D_MOONRAKER/{name}",
    "klipper-extra": "$KLIPPER_EXTRAS/{name}",
    "moonraker-component": "$MOONRAKER_COMPONENTS/{name}",
}
_KLIPPER_INSTRUMENTS = {
    "klipper-source": "$KLIPPER_SRC/{name}",
}


class KlipperPrinterJinni(Jinni):
    KLIPPER_PATH_KEYS = KLIPPER_PATH_KEYS

    def placement_destination(self, destination_class: str, name: str) -> str:
        template = _KLIPPER_PLACEMENTS.get(destination_class)
        if template is None:
            return super().placement_destination(destination_class, name)
        return template.format(name=name)

    def instrument_destination(self, instrument_class: str, name: str) -> str:
        template = _KLIPPER_INSTRUMENTS.get(instrument_class)
        if template is None:
            return super().instrument_destination(instrument_class, name)
        return template.format(name=name)

    def _candidate_ports(self) -> dict[int, str]:
        return {**inspection.GENERIC_PORTS, inspection.MOONRAKER_PORT: "Moonraker API"}

    def _print_status(self) -> tuple[bool, str]:
        return inspection.moonraker_print_state()

    def diagnose(self) -> dict:
        return {**super().diagnose(), "moonraker": inspection.port_open(inspection.MOONRAKER_PORT)}

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
