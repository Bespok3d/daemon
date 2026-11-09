# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the safety net sees when Klipper does not come back up, for tests that drive the net."""
from core.safety import AttributionIndex, FailureEvidence
from protocol import DeviceHealth, FailureSignals, ServiceHealth

KLIPPER_SERVICE = "klipper"


def printer_down() -> FailureEvidence:
    return FailureEvidence(
        health=DeviceHealth(
            services={KLIPPER_SERVICE: ServiceHealth(ready=False, detail="")},
            diagnosis="", signals=FailureSignals(),
        ),
        index=AttributionIndex(by_path={}, by_module={}, by_section={}),
    )
