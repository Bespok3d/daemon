from fastapi import APIRouter

from core.capabilities import get_capabilities
from core.selfcheck import run_selfcheck
from jinni.loader import get_jinni
from version import DAEMON_VERSION

from ..schemas import (
    CapabilitiesResponse,
    PluginDrift,
    SelfCheckResponse,
    StatusResponse,
)

router = APIRouter()


@router.get("/status", response_model=StatusResponse, summary="Daemon health check")
async def status() -> StatusResponse:
    return StatusResponse(ok=True, version=DAEMON_VERSION)


@router.get(
    "/capabilities",
    response_model=CapabilitiesResponse,
    summary="Printer capabilities",
    description="Hardware features, installed plugins, and Klipper version.",
)
async def capabilities() -> CapabilitiesResponse:
    return get_capabilities()


@router.get(
    "/selfcheck",
    response_model=SelfCheckResponse,
    summary="Compare expected on-printer plugin state to the actual filesystem",
    description=(
        "Read-only drift scan. For every active plugin, verifies that the symlinks declared "
        "in its manifest exist and point at the right source. Returns an empty drift list when "
        "everything is in order."
    ),
)
async def selfcheck() -> SelfCheckResponse:
    jinni = get_jinni()
    drift_raw = run_selfcheck(jinni.paths())
    drift = [PluginDrift(**report) for report in drift_raw]
    return SelfCheckResponse(ok=len(drift) == 0, drift=drift)
