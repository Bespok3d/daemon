# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Recovery: keep the printer working through a risky op or an OTA firmware update.

The cluster the orchestrator wires when a deferred core-service restart runs: `evidence` gathers the
post-restart state, `restart` drives the core.safety brain to verify it and auto-deactivate the
culprit, `reapply` re-applies one plugin after an OTA wipe, and `run` walks the whole installed set
in dependency order.
"""
from .reapply import ServiceLedger, recover_one
from .restart import op_context, restart_phases, restart_services
from .run import run_recovery

__all__ = [
    "op_context",
    "ServiceLedger",
    "recover_one",
    "run_recovery",
    "restart_phases",
    "restart_services",
]
