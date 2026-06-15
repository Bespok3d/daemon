"""The evidence the daemon gathers after a risky restart, and the verdict + decision over it.

Pure: `is_healthy` and the fixers judge this data; the daemon does the I/O that fills it in.
"""
from dataclasses import dataclass

from jinni.contracts import DeviceHealth

from .attribution import AttributionIndex


@dataclass
class FailureEvidence:
    """A snapshot of the printer's state after a restart, plus the attribution index for blame. The
    device-health verdict (per-service readiness, failed components, the broker) is the jinni's
    `DeviceHealth`; the log tails and the index are the daemon's own."""
    health: DeviceHealth
    klipper_log: str
    moonraker_log: str
    index: AttributionIndex


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
