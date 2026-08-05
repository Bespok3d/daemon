# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
from fastapi import APIRouter

from core import jinni_client
from core.capabilities import get_capabilities
from core.printer_identity import stored_printer_uuid
from core.selfcheck import run_selfcheck
from version import DAEMON_VERSION

from ..schemas import (
    CapabilitiesResponse,
    LicenseResponse,
    OomReportResponse,
    PluginDrift,
    PrinterProblem,
    SelfCheckResponse,
    StatusResponse,
)

DAEMON_LICENSE = "AGPL-3.0-or-later"
DAEMON_SOURCE_URL = "https://github.com/Bespok3d/daemon"

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
    summary="Compare the printer's actual state to what it should be",
    description=(
        "Read-only. Checks the conditions that make the printer work at all (its own config still "
        "includes bespok3d, the tree is whole, no plugin left half removed) and, for every "
        "active plugin, that the links its manifest declares exist and point at the right source. "
        "A printer with no plugins is checked just the same. Both lists empty means nothing is "
        "wrong; everything reported here is something POST /packages/recover puts right."
    ),
)
async def selfcheck() -> SelfCheckResponse:
    report = run_selfcheck(jinni_client.paths())
    problems = [PrinterProblem(**problem) for problem in report["problems"]]
    drift = [PluginDrift(**plugin_report) for plugin_report in report["drift"]]
    return SelfCheckResponse(
        ok=not problems and not drift,
        switched_off=report["switched_off"],
        reboot_required=report["reboot_required"],
        problems=problems,
        drift=drift,
    )


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


@router.get(
    "/license",
    response_model=LicenseResponse,
    summary="Licence and source offer for the running daemon",
    description=(
        "Read-only, and answerable without a token, because the offer it carries is owed to anyone "
        "talking to this daemon over the network. Names the licence, the version answering, and "
        "the repository holding the complete source for that version."
    ),
)
async def license_offer() -> LicenseResponse:
    return LicenseResponse(
        version=DAEMON_VERSION,
        license=DAEMON_LICENSE,
        source=DAEMON_SOURCE_URL,
        notice=(
            f"This daemon is version {DAEMON_VERSION}, free software under the GNU Affero General "
            f"Public License, version 3 or any later version. Its complete source is at "
            f"{DAEMON_SOURCE_URL}, where every release is tagged with its version. There is no "
            f"warranty, to the extent permitted by law."
        ),
    )
