"""The filesystem-layout facet of the jinni: where the bespok3d tree and the device's dirs live.

`paths()` always merges the core path variables (`BESPOK3D`, `BESPOK3D_PLUGINS`, `RUNTIME_USER`)
with whatever the device adds, so the bespok3d system's own dirs are guaranteed on every target by
construction. A device jinni overrides `device_paths()` (and may override `data_root` /
`runtime_user`) to supply its concrete host paths. The path-key contracts each tier must resolve
(`CORE_PATH_KEYS` for every target, `KLIPPER_PATH_KEYS` for a klipper printer) are this facet's, so
the loader can gate them in one place.
"""
import os
from pathlib import Path

# The path variables the bespok3d system itself needs on every device, whatever it is.
CORE_PATH_KEYS = frozenset({"BESPOK3D", "BESPOK3D_PLUGINS", "RUNTIME_USER"})

# The layout contract a klipper printer adapter must expose (the VALUES are device-specific). The
# loader strict-output gate checks these resolve for any KlipperPrinterJinni.
KLIPPER_PATH_KEYS = frozenset({
    "BESPOK3D_KLIPPER", "BESPOK3D_MOONRAKER", "KLIPPER_SRC", "KLIPPER_EXTRAS",
    "MOONRAKER_COMPONENTS", "PRINTER_CFG", "MOONRAKER_CFG",
})


class Layout:
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
