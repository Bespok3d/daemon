# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
from pydantic import BaseModel, Field


class DeactivateResponse(BaseModel):
    ok: bool = Field(description="True on success")


class TeardownResponse(BaseModel):
    ok: bool = Field(description="True on success")
