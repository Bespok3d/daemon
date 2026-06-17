from pydantic import BaseModel, Field


class StatusResponse(BaseModel):
    ok: bool = Field(description="True if the daemon is alive and healthy")
    version: str = Field(description="Daemon version string")


class InstallResponse(BaseModel):
    plugin_id: str = Field(description="ID of the installed plugin")
    ok: bool = Field(description="True on success")
    log: list[dict] = Field(default_factory=list, description="Structured per-phase install log")


class ReconfigureResponse(BaseModel):
    plugin_id: str = Field(description="ID of the reconfigured plugin")
    ok: bool = Field(description="True on success")
    log: list[dict] = Field(
        default_factory=list, description="Structured per-phase reconfigure log",
    )


class UninstallResponse(BaseModel):
    ok: bool = Field(description="True on success")
    removed: list[str] = Field(
        default_factory=list,
        description="Plugin ids removed, dependents first then the target",
    )


class PluginRecoveryResult(BaseModel):
    plugin_id: str = Field(description="Plugin that was recovered")
    ok: bool = Field(description="True if successfully recovered")
    skipped: bool = Field(default=False, description="True if skipped due to unmet dependencies")
    reason: str = Field(default="", description="Failure or skip reason")
    log: list[dict] = Field(default_factory=list, description="Per-phase install log")
    auto_deactivated: str | None = Field(
        default=None,
        description="Plugin(s) the auto-fixer deactivated to bring Klipper/Moonraker back",
    )
    fix_detail: str = Field(default="", description="The log signal that attributed the failure")


class PackResultsResponse(BaseModel):
    """The result of a pack operation (recover, update-batch, uninstall-batch): one entry per plugin
    acted on, plus a final (services) entry for the single shared restart."""

    ok: bool = Field(description="True if every plugin in the batch succeeded without hard failure")
    results: list[PluginRecoveryResult] = Field(description="Per-plugin results")


class DeactivateResponse(BaseModel):
    ok: bool = Field(description="True on success")


class TeardownResponse(BaseModel):
    ok: bool = Field(description="True on success")


class CapabilitiesResponse(BaseModel):
    adapter: str = Field(description="Adapter ID identifying the printer model")
    hardware: list[str] = Field(description="Hardware capabilities of this printer")
    installed: dict[str, str] = Field(description="Plugin ID → installed version")
    deactivated: list[str] = Field(
        default_factory=list,
        description="Installed plugins turned off (safety net or user); shown disabled, not active",
    )
    firmware_version: str = Field(description="Printer firmware version string, or 'unknown'")
    klipper_version: str = Field(
        default="unknown",
        description="Klipper version string; absent for a non-klipper device, then 'unknown'",
    )
    jinni_version: str = Field(
        default="unknown", description="Version of the adapter's jinni (its daemon-side half)"
    )
    capability_flags: list[str] = Field(
        default_factory=list, description="Capability flags the jinni advertises (e.g. overlay)"
    )
    interface_extras: list[str] = Field(
        default_factory=list,
        description="Public names the jinni exposes beyond the standard interface (caution if any)",
    )
    preferred_registries: list[str] = Field(
        description="Preferred plugin registry URLs for this adapter"
    )
    endpoints: list[dict[str, str]] = Field(
        default_factory=list,
        description="Browser-openable endpoints with {host} placeholder",
    )


class AccessRequestBody(BaseModel):
    label: str = Field(description="Friendly name for the requesting client (e.g. machine name)")
    identity: str = Field(description="GPG fingerprint (PGP on) or a stable client id (PGP off)")
    token: str = Field(description="Bearer credential the client proposes for itself")
    public_key: str | None = Field(default=None, description="Armored client public key (PGP on)")


class AccessRequestResponse(BaseModel):
    ok: bool = Field(description="True once the request is recorded as pending")
    cert: str = Field(description="The daemon's public server certificate, for the client to pin")


class AccessIdentityBody(BaseModel):
    identity: str = Field(description="Identity of the client to grant or revoke")


class AccessActionResponse(BaseModel):
    ok: bool = Field(description="True on success")


class AccessClient(BaseModel):
    identity: str = Field(description="GPG fingerprint or client id")
    role: str = Field(description="admin or user")
    label: str = Field(description="Friendly client name")


class PendingClient(BaseModel):
    identity: str = Field(description="GPG fingerprint or client id")
    label: str = Field(description="Friendly client name")
    requested_at: str = Field(description="ISO timestamp the request was recorded")


class AccessClientsResponse(BaseModel):
    clients: list[AccessClient] = Field(description="Authorized clients (no tokens exposed)")
    pending: list[PendingClient] = Field(description="Clients awaiting approval")


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
