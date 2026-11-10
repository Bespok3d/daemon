# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
from pydantic import BaseModel, Field


class FileHashesResponse(BaseModel):
    files: dict[str, str | None] = Field(
        description=(
            "The sha256 (hex) of each file the installed manifest lists as kept on disk exactly as "
            "packed, by its path inside the plugin dir. A doc/ entry, a file a template renders "
            "over, and a path the manifest does not list never appear. A kept file that is "
            "missing, unreadable, or not the plugin's own regular file is null"
        ),
    )


class RestoreFilesResponse(BaseModel):
    restored: list[str] = Field(
        description="The paths inside the plugin dir that were written back, sorted",
    )
