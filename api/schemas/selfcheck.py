# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
from pydantic import BaseModel, Field


class SymlinkIssue(BaseModel):
    kind: str = Field(description="One of: missing, not_a_symlink, wrong_target")
    link_path: str = Field(description="Absolute path where the symlink should live")
    expected_target: str | None = Field(
        default=None, description="Path the symlink should point at (missing/wrong_target)"
    )
    actual_target: str | None = Field(
        default=None, description="Path the symlink actually points at (wrong_target only)"
    )


class PluginDrift(BaseModel):
    plugin_id: str = Field(description="Plugin whose state drifted from the manifest")
    symlink_issues: list[SymlinkIssue] = Field(
        default_factory=list, description="Per-symlink drift findings for this plugin"
    )


class SelfCheckResponse(BaseModel):
    ok: bool = Field(description="True if no drift was detected for any active plugin")
    drift: list[PluginDrift] = Field(
        default_factory=list, description="Per-plugin drift reports; empty when ok=true"
    )
