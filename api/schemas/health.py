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
