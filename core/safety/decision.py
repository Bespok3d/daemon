"""The evidence the daemon gathers after a risky restart, and the verdict + decision over it.

Pure: `is_healthy` and the fixers judge this data; the daemon does the I/O that fills it in.
"""
from dataclasses import dataclass

from .attribution import AttributionIndex
from .probe.moonraker import MoonrakerInfo


@dataclass
class FailureEvidence:
    """A snapshot of the printer's state after a restart, plus the attribution index for blame."""
    klipper_reachable: bool
    klipper_log: str
    moonraker: MoonrakerInfo
    moonraker_log: str
    mqtt_up: bool
    index: AttributionIndex


@dataclass
class Decision:
    """What the safety net concluded: who to deactivate (if anyone) and why."""
    culprit: str | None
    signal: str
    fixer: str
    escaped: bool = False


def is_healthy(evidence: FailureEvidence) -> bool:
    """The printer is usable: both services answer AND Moonraker reports no failed components. The
    failed-components check is the crux: a component that fails to import leaves Moonraker reachable
    but a plugin's feature dead, which plain reachability misses."""
    return (
        evidence.klipper_reachable
        and evidence.moonraker.reachable
        and not evidence.moonraker.failed_components
    )
