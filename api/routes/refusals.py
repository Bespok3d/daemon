"""Turning an install the printer declined into the response body the app switches on.

A refusal is not a bad request and not a daemon fault: the package was understood and rejected, so
every refusal shares one status and is told apart by the `error` discriminator. The daemon relays a
reason as a TOKEN and never as prose (ADR-0037); the client owns the wording the user reads.
"""

from typing import cast

from core import packages

# Ordered as the app reads them: the reasons an install can be declined rather than failed.
REFUSALS = (
    packages.BlockedActionError,
    packages.ConflictError,
    packages.RequirementError,
    packages.IntegrityError,
)


def refusal_detail(refusal: Exception) -> dict:
    """The 409 body for a refused install: the discriminator plus what that refusal knows."""
    if isinstance(refusal, packages.BlockedActionError):
        return {"error": "blocked", "blocked_actions": refusal.blocked}
    if isinstance(refusal, packages.ConflictError):
        return {"error": "conflict", "plugin_id": refusal.plugin_id, "conflicts": refusal.conflicts}
    if isinstance(refusal, packages.RequirementError):
        return {"error": "requirement", "plugin_id": refusal.plugin_id, "missing": refusal.missing}
    integrity = cast(packages.IntegrityError, refusal)
    return {
        "error": "integrity", "plugin_id": integrity.plugin_id,
        "reason": integrity.reason, "paths": integrity.paths,
    }


def detail_text(detail: object) -> str:
    """A failed install's HTTPException detail is a plain string for most errors and a dict for a
    refusal; flatten either into a single line for the progress feed's terminal event."""
    if isinstance(detail, dict):
        return str(detail.get("error", detail))
    return str(detail)
