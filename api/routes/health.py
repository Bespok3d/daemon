from fastapi import APIRouter

from core import jinni_client
from core.capabilities import get_capabilities
from core.printer_identity import stored_printer_uuid
from core.selfcheck import run_selfcheck
from version import DAEMON_VERSION

from ..schemas import (
    CapabilitiesResponse,
    OomReportResponse,
    PluginDrift,
    SelfCheckResponse,
    StatusResponse,
)

router = APIRouter()


@router.get("/status", response_model=StatusResponse, summary="Daemon health check")
async def status() -> StatusResponse:
    return StatusResponse(
        ok=True, version=DAEMON_VERSION, printer_uuid=stored_printer_uuid(),
    )


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
    drift_raw = run_selfcheck(jinni_client.paths())
    drift = [PluginDrift(**report) for report in drift_raw]
    return SelfCheckResponse(ok=len(drift) == 0, drift=drift)


@router.get(
    "/oom",
    response_model=OomReportResponse,
    summary="Out-of-memory safety-net report",
    description=(
        "Read-only. Reports whether the kernel's out-of-memory killer has fired and, if so, the "
        "most recent victim it took. The constrained-board safety net: a client polls it and "
        "dedupes a repeat by the kill count. Detection only; the daemon prevents no OOM here."
    ),
)
async def oom() -> OomReportResponse:
    report = jinni_client.oom_report()
    return OomReportResponse(kills=report.kills, token=report.token, detail=report.detail)
