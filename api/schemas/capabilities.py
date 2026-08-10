# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
from pydantic import BaseModel, Field

from version import MIN_JINNI_VERSION


class Endpoint(BaseModel):
    """A browser-openable address a managed printer exposes (a plugin web UI, the camera stream)."""

    label: str = Field(description="Human label for the endpoint")
    url: str = Field(description="Resolved URL with a {host} placeholder the app fills in")


class KernelInfo(BaseModel):
    """The running kernel's identity, read from a loaded module via modinfo: the ground truth a
    kernel-module plugin builds a .ko against. Both fields are 'unknown' on a box reporting none."""

    release: str = Field(default="unknown", description="Kernel release (e.g. 6.1.99)")
    vermagic: str = Field(
        default="unknown",
        description="Version magic the kernel checks at insmod (release plus ABI config flags)",
    )


class CapabilitiesResponse(BaseModel):
    adapter: str = Field(description="Adapter ID identifying the printer model")
    hardware: list[str] = Field(description="Hardware capabilities of this printer")
    installed: dict[str, str] = Field(description="Plugin ID → installed version")
    deactivated: list[str] = Field(
        default_factory=list,
        description="Installed plugins turned off (safety net or user); shown disabled, not active",
    )
    stored_signatures: list[str] = Field(
        default_factory=list,
        description="Installed plugins still holding the manifest signature their package shipped; "
                    "presence on disk only, never a verification result",
    )
    firmware_version: str = Field(description="Printer firmware version string, or 'unknown'")
    arch: str = Field(
        default="unknown",
        description="CPU architecture native artifacts target (e.g. aarch64); a variant dimension",
    )
    board_class: str = Field(
        default="unknown",
        description="Board resource tier: 'standard', 'constrained' (memory-starved), or 'unknown'",
    )
    kernel: KernelInfo = Field(
        default_factory=KernelInfo,
        description="Running kernel release + version magic (modinfo ground truth for a .ko build)",
    )
    klipper_version: str = Field(
        default="unknown",
        description="Klipper version string; absent for a non-klipper device, then 'unknown'",
    )
    jinni_version: str = Field(
        default="unknown", description="Version of the adapter's jinni (its daemon-side half)"
    )
    min_jinni_version: str = Field(
        default=MIN_JINNI_VERSION,
        description="Oldest jinni this daemon will drive; the app refuses an older pair",
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
