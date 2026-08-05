# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The generic-box fake jinni: a plain linux box, no klipper services, vacuously healthy.

The daemon's generic install path is tested against this, exactly as the loader's generic fallback
would answer over the socket. It is the klipper fake narrowed to the bespok3d-layout placement
classes only, so it lives beside `fakes.py` (the klipper fake it extends) as its own device profile.
"""
from protocol import CommandEffect, DeviceHealth
from tests import fake_vocab
from tests.fakes import FakeKlipperJinni


class FakeGenericJinni(FakeKlipperJinni):
    id = "fake-generic"

    def placement_destination(self, destination_class: str, name: str) -> str:
        if destination_class not in ("system-bin", "web-location"):
            raise ValueError(f"unsupported destination class: {destination_class}")
        return fake_vocab.PLACEMENTS[destination_class].format(name=name)

    def classify_commands(self, commands: list[str]) -> list[CommandEffect]:
        return [CommandEffect(deferrable=False, restarts_services=(), blocking_token=None)
                for _ in commands]

    def restart_command(self, hook: str) -> str | None:
        return None

    def bespok3d_include_status(self) -> dict[str, bool]:
        """A generic box has no config of its own to wire, so it reports nothing to check, exactly
        as the real generic integration does."""
        return {}

    def capability_flags(self) -> set[str]:
        return set()

    def health(self) -> DeviceHealth:
        return DeviceHealth(services={})

    def capabilities(self) -> dict:
        report = super().capabilities()
        report.update(adapter=self.id, capability_flags=[])
        report.pop("klipper_version")
        return report
