# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The order a plugin's boot scripts start in: the daemon's only say in the init system.

A managed service (ADR-0026/0029) and a kernel-module loader (ADR-0039) are each realized by the
adapter generating a boot script the daemon writes under the plugin and registers for boot. The
daemon's whole contribution is the ORDER: a module is loaded before a service is started, so a
service that needs the module finds it there. It says that by naming the tier and nothing more; the
jinni answers where the script lives and which words drive it (ADR-0037), so no init system, no
prefix and no registration path is named in core.

Both tiers are driven with `restart` (unload/stop then load/start), so an update shipping a changed
script or `.ko` takes effect at once, not after a reboot; the boot runner still drives them with
plain `start`. `intent.py` folds the produced symlinks/starts/stops in.
"""
from collections.abc import Callable

from core import jinni_client

BOOT_TIER_KERNEL_MODULE = "kernel-module"
BOOT_TIER_SERVICE = "service"
BOOT_TIERS_IN_START_ORDER = (BOOT_TIER_KERNEL_MODULE, BOOT_TIER_SERVICE)


def service_placement(service: dict) -> dict[str, str]:
    return jinni_client.service_status(service["name"], BOOT_TIER_SERVICE)


def kmodule_placement(kmodule: dict) -> dict[str, str]:
    return jinni_client.service_status(kmodule["name"], BOOT_TIER_KERNEL_MODULE)


def _autostart_ops(name: str, tier: str, active: bool) -> tuple[dict, str | None, str]:
    """Return (registration_symlink, start_command_or_None, stop_command) for one boot script."""
    start = jinni_client.service_control(name, tier, "restart") if active else None
    stop = jinni_client.service_deregister(name, tier)["stop"]
    return jinni_client.service_register(name, tier), start, stop


def service_ops(service: dict) -> tuple[dict, str | None, str]:
    return _autostart_ops(service["name"], BOOT_TIER_SERVICE, bool(service.get("autostart")))


def kmodule_ops(kmodule: dict) -> tuple[dict, str | None, str]:
    return _autostart_ops(kmodule["name"], BOOT_TIER_KERNEL_MODULE, bool(kmodule.get("autoload")))


def autostart_additions(
    entries: list[dict], ops: Callable[[dict], tuple[dict, str | None, str]]
) -> tuple[list[dict], list[str], list[str]]:
    """Collect one autostart family's (symlinks, start_commands, stop_commands): every entry wires a
    symlink and a stop, and an active one adds a start."""
    symlinks: list[dict] = []
    starts: list[str] = []
    stops: list[str] = []
    for entry in entries:
        symlink_op, start_cmd, stop_cmd = ops(entry)
        symlinks.append(symlink_op)
        if start_cmd is not None:
            starts.append(start_cmd)
        stops.append(stop_cmd)
    return symlinks, starts, stops
