# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The app<->daemon JSON response contract, split by concern. Importers keep their
`from api.schemas import X`; each model lives in the sibling file for its concern (health, packages,
capabilities, lifecycle, access, selfcheck). The wire shapes the app parses raw are pinned by the
golden fixture (tests/api/test_contract_fixture.py + contract_fixture.json) against contract.ts.
"""
from .access import (
    AccessActionResponse,
    AccessClient,
    AccessClientsResponse,
    AccessIdentityBody,
    AccessRequestBody,
    AccessRequestResponse,
    PendingClient,
)
from .capabilities import CapabilitiesResponse, Endpoint, KernelInfo
from .health import LicenseResponse, OomReportResponse, StatusResponse
from .lifecycle import DeactivateResponse, TeardownResponse
from .packages import (
    InstallLogItem,
    InstallLogPhase,
    InstallResponse,
    PackResultsResponse,
    PluginConfigResponse,
    PluginDeactivateResponse,
    PluginRecoveryResult,
    ReconfigureResponse,
    UninstallResponse,
)
from .selfcheck import PluginDrift, PrinterProblem, SelfCheckResponse, SymlinkIssue

__all__ = [
    "AccessActionResponse",
    "AccessClient",
    "AccessClientsResponse",
    "AccessIdentityBody",
    "AccessRequestBody",
    "AccessRequestResponse",
    "CapabilitiesResponse",
    "DeactivateResponse",
    "Endpoint",
    "InstallLogItem",
    "InstallLogPhase",
    "InstallResponse",
    "KernelInfo",
    "LicenseResponse",
    "OomReportResponse",
    "PackResultsResponse",
    "PendingClient",
    "PluginConfigResponse",
    "PluginDeactivateResponse",
    "PluginDrift",
    "PrinterProblem",
    "PluginRecoveryResult",
    "ReconfigureResponse",
    "SelfCheckResponse",
    "StatusResponse",
    "SymlinkIssue",
    "TeardownResponse",
    "UninstallResponse",
]
