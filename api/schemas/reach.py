# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
from pydantic import BaseModel, Field


class WebReachBody(BaseModel):
    url: str = Field(description="The web address to try from the printer, as the user typed it")


class WebReachResponse(BaseModel):
    http_code: int | None = Field(
        description=(
            "The http code the address answered the printer with, after redirects; null when "
            "nothing answered (no route, refused, timed out, or not a usable address)"
        ),
    )
