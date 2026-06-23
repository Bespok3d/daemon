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
from .capabilities import CapabilitiesResponse, Endpoint
from .health import StatusResponse
from .lifecycle import DeactivateResponse, TeardownResponse
from .packages import (
    InstallLogItem,
    InstallLogPhase,
    InstallResponse,
    PackResultsResponse,
    PluginRecoveryResult,
    ReconfigureResponse,
    UninstallResponse,
)
from .selfcheck import PluginDrift, SelfCheckResponse, SymlinkIssue

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
    "PackResultsResponse",
    "PendingClient",
    "PluginDrift",
    "PluginRecoveryResult",
    "ReconfigureResponse",
    "SelfCheckResponse",
    "StatusResponse",
    "SymlinkIssue",
    "TeardownResponse",
    "UninstallResponse",
]
