# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Duck-typed fake jinnis for the daemon's isolation tests: answer the protocol verbs in-process so
the daemon's orchestration is tested ALONE, exactly as a real jinni would answer over the socket
(the daemon never imports the jinni runtime). The verb classification lives in `fake_vocab`, the
device actuation in `fake_actuation` / `fake_integration`; this file is just the two duck-typed
classes that wire those into the contract surface.
"""
from collections.abc import AsyncIterator
from pathlib import Path

from protocol import ActionResult, CommandEffect, DeviceHealth, OomReport, ServiceHealth
from tests import fake_actuation, fake_integration, fake_vocab


class FakeKlipperJinni:
    """A klipper printer jinni as the daemon sees it over the socket. `paths_override` lets a test
    point the klipper paths at a real tmp tree, the way a real device jinni's own paths() would."""
    id = "fake-klipper"

    def __init__(self) -> None:
        self.paths_override: dict[str, str] = {}

    def paths(self) -> dict[str, str]:
        core = {"BESPOK3D": "/userdata/bespok3d",
                "BESPOK3D_PLUGINS": "/userdata/bespok3d/usr/local/plugins",
                "RUNTIME_USER": "lava"}
        klipper = {key: f"/dev/null/{key}" for key in fake_vocab.KLIPPER_PATH_KEYS}
        return {**core, **klipper, **self.paths_override}

    def placement_destination(self, destination_class: str, name: str) -> str:
        template = fake_vocab.PLACEMENTS.get(destination_class)
        if template is None:
            raise ValueError(f"unsupported destination class: {destination_class}")
        return template.format(name=name)

    def instrument_destination(self, instrument_class: str, name: str) -> str:
        template = fake_vocab.INSTRUMENTS.get(instrument_class)
        if template is None:
            raise ValueError(f"unsupported instrument class: {instrument_class}")
        return template.format(name=name)

    def restart_command(self, hook: str) -> str | None:
        return fake_vocab.RESTART_COMMANDS.get(hook)

    def classify_commands(self, commands: list[str]) -> list[CommandEffect]:
        return [fake_vocab.classify(command) for command in commands]

    def run_actions(self, commands: list[str]) -> list[ActionResult]:
        """Run each command for real, as the device jinni would. A suite needing a deterministic
        result (a restart with no real service) monkeypatches this."""
        return fake_actuation.run_actions(commands)

    def wire(self, plugin_dir: str, links: list[dict]) -> list[ActionResult]:
        return fake_actuation.wire(plugin_dir, links)

    def unwire(self, plugin_dir: str, destinations: list[str]) -> list[ActionResult]:
        return fake_actuation.unwire(plugin_dir, destinations)

    def fetch(self, path: str) -> str | None:
        target = Path(path)
        return target.read_bytes().decode(errors="replace") if target.is_file() else None

    def write_files(self, plugin_dir: str, writes: list[dict]) -> list[ActionResult]:
        return fake_actuation.write_files(plugin_dir, writes)

    def prune_dead_config_links(self) -> list[str]:
        paths = self.paths()
        return fake_integration.prune_dead_links(
            [paths[key] for key in ("BESPOK3D_KLIPPER", "BESPOK3D_MOONRAKER") if paths.get(key)]
        )

    def remove_bespok3d_includes(self) -> None:
        paths = self.paths()
        fake_integration.remove_includes(paths["PRINTER_CFG"], paths["MOONRAKER_CFG"])

    def restore_bespok3d_includes(self) -> None:
        paths = self.paths()
        fake_integration.restore_includes(paths["PRINTER_CFG"], paths["MOONRAKER_CFG"])

    def prune_bespok3d_config_dir(self) -> None:
        fake_integration.prune_config_dir(self.paths()["BESPOK3D_KLIPPER"])

    def bespok3d_include_status(self) -> dict[str, bool]:
        paths = self.paths()
        return fake_integration.include_status(paths["PRINTER_CFG"], paths["MOONRAKER_CFG"])

    def render_service_script(self, service: dict, paths: dict[str, str]) -> str:
        return f"#gen {service['name']} {service['command']}"

    def render_module_script(self, kmodule: dict, paths: dict[str, str]) -> str:
        return f"#kmod {kmodule['name']} {kmodule['module']}"

    def device_node_present(self, path: str) -> bool:
        return Path(path).exists()

    def classify_module_load(self, name: str) -> str:
        """No known cause by default; a suite proving the vermagic-mismatch path overrides this."""
        return ""

    def capability_flags(self) -> set[str]:
        return {"overlay", "managed-service"}

    def variant_facts(self) -> dict[str, str]:
        return {"adapter": self.id, "firmware_version": "unknown", "arch": "aarch64",
                "board_class": "standard", "kernel_release": "6.1.99",
                "vermagic": "6.1.99 SMP preempt mod_unload aarch64"}

    def startup_control_scripts(self, paths: dict[str, str]) -> list:
        return []

    def background_tasks(self) -> list:
        return []

    def health(self) -> DeviceHealth:
        return DeviceHealth(services={
            fake_vocab.KLIPPER: ServiceHealth(ready=True, detail="ready"),
            fake_vocab.MOONRAKER: ServiceHealth(ready=True, detail="up"),
        })

    def oom_report(self) -> OomReport:
        """No out-of-memory kill by default; a suite proving the report path overrides this."""
        return OomReport(kills=0)

    def print_active(self) -> tuple[bool, str]:
        return False, ""

    def is_active_print_state(self, state: str) -> bool:
        return state in ("printing", "paused")

    def blocked_actions(self) -> frozenset[str]:
        _active, state = self.print_active()
        if not self.is_active_print_state(state):
            return frozenset()
        return frozenset({fake_vocab.RESTART_KLIPPER, fake_vocab.RESTART_MOONRAKER,
                          fake_vocab.RESTART_DISPLAY})

    async def watch_blocked_actions(self) -> AsyncIterator[frozenset[str]]:
        yield self.blocked_actions()

    def capabilities(self) -> dict:
        magic = "6.1.99 SMP preempt mod_unload aarch64"
        return {"adapter": self.id, "hardware": [], "installed": {}, "deactivated": [],
                "firmware_version": "unknown", "arch": "aarch64", "board_class": "standard",
                "kernel": {"release": "6.1.99", "vermagic": magic},
                "jinni_version": "fake", "capability_flags": [],
                "preferred_registries": [], "endpoints": [], "klipper_version": "0.0-fake"}

    def version(self) -> str:
        return "fake"
