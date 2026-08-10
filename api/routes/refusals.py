# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Turning an install the printer declined into the response body the app switches on.

A refusal is not a bad request and not a daemon fault: the package was understood and rejected, so
every refusal shares one status and is told apart by the `error` discriminator. The daemon relays a
reason as a TOKEN and never as prose (ADR-0037); the client owns the wording the user reads.
"""

from typing import cast

from core import packages

# Ordered as the app reads them: the reasons an install can be declined rather than failed.
REFUSALS = (
    packages.IncompatiblePairError,
    packages.BlockedActionError,
    packages.ConflictError,
    packages.RequirementError,
    packages.IntegrityError,
)


def refusal_detail(refusal: Exception) -> dict:
    """The 409 body for a refused install: the discriminator plus what that refusal knows.

    The first refusal is about the PRINTER, not the package: this daemon and this printer's jinni do
    not fit together, so no package would have installed. It names the side that is behind and both
    versions, and the client turns that into the sentence telling the user which half to update."""
    if isinstance(refusal, packages.IncompatiblePairError):
        return {
            "error": "incompatible_pair", "side": refusal.side,
            "required": refusal.required, "running": refusal.running,
        }

    return _package_refusal_detail(refusal)


def _package_refusal_detail(refusal: Exception) -> dict:
    """The refusals about the package itself: what it would block, what it collides with, what it
    needs and has not got, and whether its bytes are what it claims they are."""
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
