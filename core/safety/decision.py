# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The evidence the daemon gathers after a risky restart, and the verdict + decision over it.

Pure: `is_healthy` and the fixers judge this data; the daemon does the I/O that fills it in.
"""
from dataclasses import dataclass

from protocol import DeviceHealth

from .attribution import AttributionIndex


@dataclass
class FailureEvidence:
    """A snapshot of the printer's state after a restart, plus the attribution index for blame. The
    device-health verdict (per-service readiness, failed components, the failure signals read from
    the device logs, the user-facing tail) is the jinni's `DeviceHealth`; the index, which plugin
    placed what, is the daemon's own.

    `module_diagnosis` is the jinni's token for a kernel-module load that failed in its own install
    phase (never a core-service restart, so it does not surface in `health`): the OTA-kernel-bump
    path fills it in and the kernel_module_failure fixer names the plugin from it. Empty on the
    normal restart-health path."""
    health: DeviceHealth
    index: AttributionIndex
    module_diagnosis: str = ""


@dataclass
class Decision:
    """What the safety net concluded: who to deactivate (if anyone) and why."""
    culprit: str | None
    signal: str
    fixer: str
    escaped: bool = False


def is_healthy(evidence: FailureEvidence) -> bool:
    """The printer is usable: every service ready AND none reporting a failed component. The
    failed-components check is the crux: a component that fails to import leaves Moonraker reachable
    but a plugin's feature dead, which plain reachability misses. The jinni's report already encodes
    this in `DeviceHealth.healthy`."""
    return evidence.health.healthy
