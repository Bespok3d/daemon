# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The services facet of the fake jinni: SysV answers, the same ones the klipper jinni gives.

The daemon never imports the jinni runtime, so the core tests answer the four service verbs here.
Kept in its own module because it is the one part of the fake that a systemd tier would replace
wholesale, exactly as the real jinni composes its facets.
"""


class FakeSysVServices:
    _BOOT_TIER_PREFIXES = {"kernel-module": "s05", "service": "s65"}

    def service_status(self, name: str, tier: str) -> dict[str, str]:
        script = f"{self._BOOT_TIER_PREFIXES[tier]}{name}"
        return {
            "script": script,
            "source": f"etc/init.d/{script}",
            "destination": f"$BESPOK3D/etc/init.d/autostart/{script}",
        }

    def service_register(self, name: str, tier: str) -> dict[str, str]:
        placement = self.service_status(name, tier)
        return {"from": placement["source"], "to": placement["destination"]}

    def service_deregister(self, name: str, tier: str) -> dict[str, str]:
        return {
            "stop": self.service_control(name, tier, "stop"),
            "registration": self.service_status(name, tier)["destination"],
        }

    def service_control(self, name: str, tier: str, action: str) -> str:
        return f"{self.service_status(name, tier)['destination']} {action}"
