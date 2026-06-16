"""The daemon safety net: detect and recover from a risky operation that breaks a core service.

The daemon does the risky thing (places files, restarts services), then hands the gathered evidence
and what it was doing to this package and asks: is the printer still usable, and if not, who broke
it? The decision logic here is pure - all I/O (probing, deactivating, restarting) stays in the
daemon, which acts on the verdict and reports it to the app.

Public surface:
- `decide(evidence, ctx)` -> the culprit + reason (walks the fixer chain; the catch-all guarantees
  a decision always comes back).
- `is_healthy(evidence)` -> the stronger verdict (reachable AND no failed components).
- data types the daemon fills in: `OperationContext`, `OperationKind`, `FailureEvidence`,
  `Decision`, `Placement`, `AttributionIndex`. The device-health verdict it carries is the jinni's
  `jinni.contracts.DeviceHealth`.
"""
from .attribution import AttributionIndex, Placement, attribute, build_index
from .context import OperationContext, OperationKind
from .decision import Decision, FailureEvidence, is_healthy
from .net import decide

__all__ = [
    "decide",
    "is_healthy",
    "OperationContext",
    "OperationKind",
    "FailureEvidence",
    "Decision",
    "Placement",
    "AttributionIndex",
    "attribute",
    "build_index",
]
