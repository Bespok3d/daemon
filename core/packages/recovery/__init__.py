"""Recovery: keep the printer working through a risky op or an OTA firmware update.

The cluster the orchestrator wires when a deferred core-service restart runs: `evidence` gathers the
post-restart state, `restart` drives the core.safety brain to verify it and auto-deactivate the
culprit, and `reapply` re-applies every installed plugin after an OTA wipe.
"""
from .restart import op_context, restart_phases, restart_services

__all__ = [
    "op_context",
    "restart_phases",
    "restart_services",
]
