# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
from pydantic import BaseModel, Field


class StatusResponse(BaseModel):
    ok: bool = Field(description="True if the daemon is alive and healthy")
    version: str = Field(description="Daemon version string")
    printer_uuid: str | None = Field(
        default=None,
        description=(
            "Stable printer identity, minted once at first startup and persisted in the data "
            "root (survives OTA); null until the daemon has a data root to keep it in"
        ),
    )


class OomReportResponse(BaseModel):
    kills: int = Field(
        description=(
            "Kernel cumulative oom_kill counter since boot; 0 when the killer has not fired. A "
            "client dedupes a repeat report by the delta against the count it last saw."
        ),
    )
    token: str = Field(
        default="",
        description=(
            "Machine token the app localizes: 'oom-kill' when the out-of-memory killer fired, or "
            "'' when nothing was killed. Whether the victim was a core service or a plugin is not "
            "classified here (see ADR-0040); read `detail` for the victim."
        ),
    )
    detail: str = Field(
        default="",
        description="Human-readable victim line for the user, or '' when the victim is unknown.",
    )


class LicenseResponse(BaseModel):
    """The AGPL section 13 offer: a network user of this daemon can find the source for the exact
    version answering them."""

    version: str = Field(description="Daemon version this offer is about")
    license: str = Field(description="SPDX identifier of the licence this daemon is under")
    source: str = Field(
        description="Public repository holding the complete source for every released version",
    )
    notice: str = Field(
        description="The offer in words, naming where the source for this running version is",
    )
