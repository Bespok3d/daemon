from pydantic import BaseModel, Field


class Endpoint(BaseModel):
    """A browser-openable address a managed printer exposes (a plugin web UI, the camera stream)."""

    label: str = Field(description="Human label for the endpoint")
    url: str = Field(description="Resolved URL with a {host} placeholder the app fills in")


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
    endpoints: list[Endpoint] = Field(
        default_factory=list,
        description="Browser-openable endpoints with {host} placeholder",
    )
