from pydantic import BaseModel, Field


class StatusResponse(BaseModel):
    ok: bool = Field(description="True if the daemon is alive and healthy")
    version: str = Field(description="Daemon version string")
