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


class PrinterProblem(BaseModel):
    kind: str = Field(
        description="One of: includes_missing, includes_present_while_off, directory_missing, "
                    "plugin_half_removed, plugin_recovery_failed"
    )
    detail: str = Field(
        description="What the problem is about: a config name, a directory, or a plugin id"
    )
    plugin_id: str | None = Field(
        default=None, description="Plugin the problem belongs to, when it belongs to one"
    )


class SelfCheckResponse(BaseModel):
    ok: bool = Field(description="True if the printer is sound and no active plugin drifted")
    switched_off: bool = Field(
        default=False,
        description="True when the user switched bespok3d off on this printer: its config "
                    "includes are gone and its plugins are unlinked on purpose. Not a problem, "
                    "and ok stays true, but a caller must show it rather than a clean bill.",
    )
    reboot_required: list[str] = Field(
        default_factory=list,
        description="Tokens for the states this printer has got into that only a power cycle "
                    "clears, as its own jinni names them. Empty on a printer whose jinni "
                    "recognises none. A caller shows the reason and offers the reboot; it never "
                    "reboots on its own.",
    )
    problems: list[PrinterProblem] = Field(
        default_factory=list,
        description="Printer-level problems that belong to no single plugin; empty when ok=true",
    )
    drift: list[PluginDrift] = Field(
        default_factory=list, description="Per-plugin drift reports; empty when ok=true"
    )
