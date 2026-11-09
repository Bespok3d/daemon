# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Recovery: keep the printer working through a risky op or an OTA firmware update.

The cluster the orchestrator wires when a deferred core-service restart runs: `evidence` gathers the
post-restart state, `restart` drives the core.safety brain to verify it and auto-deactivate the
culprit, `reapply` re-applies one plugin after an OTA wipe, and `run` walks the whole installed set
in dependency order (`turn_order` lets a plugin wait for a provider still to come back). `put_back`
names the plugins the safety net switched off, which recovery re-applies too, and `stale_originals`
makes the kept files of the plugins that stay off the new firmware's.
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
