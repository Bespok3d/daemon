# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The init-system half of the jinni contract surface (ADR-0037): where the device keeps a plugin's
boot scripts, and the words that drive one.

The daemon names a TIER (`kernel-module` or `service`), which carries its ordering intent and
nothing else; every init-system fact (the script name, the registration path, the start and stop
words) is the jinni's answer. That is what lets a systemd box answer with a unit file and
`systemctl` without a line changing here. Read verbs: the daemon executes what they describe through
the actuation verbs in `actuation.py`.
"""
from typing import cast

from .dispatch import route


def service_status(name: str, tier: str) -> dict[str, str]:
    """Where the device's init system keeps one plugin boot script: the name it takes, the path it
    is written to inside the plugin, and the path that registers it for boot. The daemon supplies
    only the tier ('kernel-module' or 'service'), which carries its ordering intent and nothing
    about the init system itself."""
    return cast(dict[str, str], route("service_status", [name, tier]))


def service_register(name: str, tier: str) -> dict[str, str]:
    return cast(dict[str, str], route("service_register", [name, tier]))


def service_deregister(name: str, tier: str) -> dict[str, str]:
    return cast(dict[str, str], route("service_deregister", [name, tier]))


def service_control(name: str, tier: str, action: str) -> str:
    return cast(str, route("service_control", [name, tier, action]))
