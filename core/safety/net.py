# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Decide what is wrong and who to blame. Pure: the daemon gathers evidence and acts on the verdict.

`decide` walks the fixer chain and returns the first hit; the chain ends in a catch-all so a
decision always comes back. The daemon keeps the I/O and the deactivation - it does the thing, then
asks here what happened and reports it.
"""
from .context import OperationContext
from .decision import Decision, FailureEvidence
from .fixers import default_chain


def decide(evidence: FailureEvidence, ctx: OperationContext,
           already: list[str] | None = None) -> Decision:
    seen = list(already or [])
    for fixer in default_chain():
        decision = fixer(evidence, ctx, seen)
        if decision is not None:
            return decision
    # Unreachable: the catch-all always returns. Kept so the type is total.
    return Decision(None, "no decision", "none", escaped=True)
