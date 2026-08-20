# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
from pydantic import BaseModel, Field


class InstallLogItem(BaseModel):
    """One step inside an install phase: built by core.results.item()."""

    label: str = Field(description="What this step did")
    ok: bool = Field(description="True if the step succeeded")
    output: str = Field(default="", description="Captured output for the step, truncated")


class InstallLogPhase(BaseModel):
    """A group of install steps, ok only if every item is: built by core.results.phase()."""

    id: str = Field(description="Stable phase id (e.g. extract, place, restart)")
    label: str = Field(description="Human label for the phase")
    ok: bool = Field(description="True only if every item in the phase succeeded")
    items: list[InstallLogItem] = Field(default_factory=list, description="Steps in this phase")


class InstallResponse(BaseModel):
    plugin_id: str = Field(description="ID of the installed plugin")
    ok: bool = Field(description="True on success")
    log: list[InstallLogPhase] = Field(
        default_factory=list, description="Structured per-phase install log"
    )


class ReconfigureResponse(BaseModel):
    plugin_id: str = Field(description="ID of the reconfigured plugin")
    ok: bool = Field(description="True on success")
    log: list[InstallLogPhase] = Field(
        default_factory=list, description="Structured per-phase reconfigure log",
    )


class UninstallResponse(BaseModel):
    ok: bool = Field(description="True on success")
    removed: list[str] = Field(
        default_factory=list,
        description="Plugin ids removed, dependents first then the target",
    )


class PluginDeactivateResponse(BaseModel):
    ok: bool = Field(description="True on success")
    deactivated: list[str] = Field(
        default_factory=list,
        description="Plugin ids deactivated, dependents first then the target",
    )


class PluginConfigResponse(BaseModel):
    vars: dict[str, str] = Field(
        default_factory=dict,
        description="The plugin's persisted install-time user variables, empty if it took none",
    )


class PluginRecoveryResult(BaseModel):
    plugin_id: str = Field(description="Plugin that was recovered")
    ok: bool = Field(description="True if successfully recovered")
    skipped: bool = Field(default=False, description="True if skipped due to unmet dependencies")
    reason: str = Field(default="", description="Failure or skip reason")
    log: list[InstallLogPhase] = Field(default_factory=list, description="Per-phase install log")
    auto_deactivated: str | None = Field(
        default=None,
        description="Plugin(s) the auto-fixer deactivated to bring Klipper/Moonraker back",
    )
    fix_detail: str = Field(default="", description="The log signal that attributed the failure")
    changed_files: list[str] = Field(default_factory=list, description="The plugin's own files another plugin changed on the printer; recovery reports them and carries on")  # noqa: E501


class PackResultsResponse(BaseModel):
    """The result of a pack operation (recover, update-batch, uninstall-batch): one entry per plugin
    acted on, plus a final (services) entry for the single shared restart."""

    ok: bool = Field(description="True if every plugin in the batch succeeded without hard failure")
    results: list[PluginRecoveryResult] = Field(description="Per-plugin results")
