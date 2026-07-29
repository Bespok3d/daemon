# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Capabilities: what this printer can do.

The daemon just consumes them: it asks the jinni (through the seam) for the target's facts.
"""

from api.schemas import CapabilitiesResponse
from core import jinni_client
from core.packages import PLUGIN_ROOT
from core.packages.signatures import plugins_with_stored_signature


def get_capabilities() -> CapabilitiesResponse:
    """The target's facts from the jinni, plus the one capability the daemon answers itself: which
    installed plugins still hold the detached signature they shipped with (ADR-0037 gives the daemon
    the filesystem, so a filesystem fact is not worth a round trip through the jinni)."""
    return CapabilitiesResponse(
        **jinni_client.capabilities_report(),
        stored_signatures=plugins_with_stored_signature(PLUGIN_ROOT),
    )
