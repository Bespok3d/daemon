from pydantic import BaseModel, Field


class DeactivateResponse(BaseModel):
    ok: bool = Field(description="True on success")


class TeardownResponse(BaseModel):
    ok: bool = Field(description="True on success")
