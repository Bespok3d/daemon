"""Attribute a failed kernel-module load through the same fixer chain the restart safety net uses.

A kernel-module load fails in its own install phase (never a core-service restart), so it does not
reach the restart-health path. This bridges the jinni's load-failure token into the one attribution
brain: `decide` walks the chain over synthetic evidence carrying the token, and the
kernel_module_failure fixer names the plugin the op is applying and relays the token. None when the
token is empty (no known cause), so the caller keeps its generic reason. The kernel analogue of the
python auto-deactivate reporting a descriptive dep failure instead of a bare 'phase failed'.
"""
from protocol import DeviceHealth

from .attribution import AttributionIndex
from .context import OperationContext
from .decision import Decision, FailureEvidence
from .net import decide

_KERNEL_MODULE_FIXER = "kernel-module-failure"
_NO_ATTRIBUTION = AttributionIndex(by_path={}, by_module={}, by_section={})


def diagnose_module_failure(diagnosis: str, ctx: OperationContext) -> Decision | None:
    """The Decision the kernel_module_failure fixer reaches for this load-failure token, or None
    when the token is empty or the chain did not attribute it there."""
    if not diagnosis:
        return None
    evidence = FailureEvidence(
        health=DeviceHealth(services={}), index=_NO_ATTRIBUTION, module_diagnosis=diagnosis
    )
    decision = decide(evidence, ctx)
    return decision if decision.fixer == _KERNEL_MODULE_FIXER else None
