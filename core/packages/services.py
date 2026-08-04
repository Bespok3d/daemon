# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Services: generate the managed-service init scripts the adapter knows how to write.

A service script is only generated when the printer's jinni advertises managed-service support; the
script body itself comes from the jinni so the daemon names no concrete init format.
"""

from pathlib import Path

from .. import jinni_client
from ..autostart import service_placement
from ..results import item, phase
from .init_scripts import write_init_script
from .user_vars import expand


def _expand_service(service: dict, vars: dict[str, str]) -> dict:
    return {
        **service,
        "command": expand(service["command"], vars),
        "args": [expand(arg, vars) for arg in service.get("args", [])],
    }


def _write_one_service_script(service: dict, plugin_dir: Path, vars: dict[str, str], flags: set[str]) -> dict:  # noqa: E501
    placement = service_placement(service)
    if "managed-service" not in flags:
        return item(f"{placement['script']}: managed services not supported on this printer", ok=False)  # noqa: E501
    return write_init_script(
        plugin_dir, placement,
        lambda: jinni_client.render_service_script(_expand_service(service, vars), vars),
    )


def generate_service_scripts(services: list[dict], plugin_dir: Path, vars: dict[str, str]) -> dict:
    flags = jinni_client.capability_flags()
    items = [_write_one_service_script(service, plugin_dir, vars, flags) for service in services]
    return phase("services", "Services", items)
