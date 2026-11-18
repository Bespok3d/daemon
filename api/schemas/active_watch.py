# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
from pydantic import BaseModel, Field

from core.watch.settings import RemedyChoice


class ActiveWatchSetting(BaseModel):
    enabled: bool = Field(description="Whether the printer watches its live logs")
    files: list[str] = Field(description="The log files the printer watches, by path")
    remedies: dict[str, RemedyChoice] = Field(
        description=(
            "What the printer does for each state its jinni recognises, by token: notify the app, "
            "or reboot when nothing is printing. Every state the printer can recognise is listed"
        ),
    )

