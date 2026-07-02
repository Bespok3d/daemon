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
