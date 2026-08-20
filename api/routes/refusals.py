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
    packages.MissingSettingError,
    packages.IntegrityError,
)


# The token the app switches on, and what each one calls its list of names.
_NAMED_LIST_REFUSALS: dict[type[Exception], tuple[str, str]] = {
    packages.ConflictError: ("conflict", "conflicts"),
    packages.RequirementError: ("requirement", "missing"),
    packages.MissingSettingError: ("missing_setting", "missing"),
}


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
    """The refusals about the package itself: what it would block, whether its bytes are what it
    claims, and the three that each name a plugin and a list it fell down on."""
    if isinstance(refusal, packages.BlockedActionError):
        return {"error": "blocked", "blocked_actions": refusal.blocked}
    if isinstance(refusal, packages.IntegrityError):
        return {
            "error": "integrity", "plugin_id": refusal.plugin_id,
            "reason": refusal.reason, "paths": refusal.paths,
        }
    return _named_list_detail(refusal)


def _named_list_detail(refusal: Exception) -> dict:
    """The refusals that say which plugin was declined and which names it fell down on: what it
    collides with, what service it needs, what setting it needs. They differ only in the token and
    in what that list of names is called, so the table carries both rather than a branch each."""
    token, list_key = _NAMED_LIST_REFUSALS[type(refusal)]
    named = cast(packages.RequirementError, refusal)
    return {"error": token, "plugin_id": named.plugin_id, list_key: getattr(refusal, list_key)}


def detail_text(detail: object) -> str:
    """A failed install's HTTPException detail is a plain string for most errors and a dict for a
    refusal; flatten either into a single line for the progress feed's terminal event."""
    if isinstance(detail, dict):
        return str(detail.get("error", detail))
    return str(detail)
