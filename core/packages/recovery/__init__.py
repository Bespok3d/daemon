# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Recovery: keep the printer working through a risky op or an OTA firmware update.

The cluster the orchestrator wires when a deferred core-service restart runs: `evidence` gathers the
post-restart state, `restart` drives the core.safety brain to verify it and auto-deactivate the
culprit, `reapply` re-applies one plugin after an OTA wipe, `run` walks the whole installed set in
dependency order, and `reboot_replaces` keeps the net's check for after a reboot.
"""
from .phases import restart_phases
from .reapply import ServiceLedger, recover_one
from .reboot_replaces import check_after_reboot
from .restart import op_context, restart_services
from .run import run_recovery

__all__ = [
    "check_after_reboot",
    "op_context",
    "ServiceLedger",
    "recover_one",
    "run_recovery",
    "restart_phases",
    "restart_services",
]
