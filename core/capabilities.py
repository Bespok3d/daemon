"""
Capabilities: what this printer can do.

The daemon just consumes them: it asks the adapter's jinni for the target's facts.
"""

from api.schemas import CapabilitiesResponse
from jinni import interface_extras
from jinni.loader import get_jinni


def get_capabilities() -> CapabilitiesResponse:
    jinni = get_jinni()
    # interface_extras is computed here, not from the jinni's self-report, so a custom adapter
    # cannot conceal that it exposes behaviour beyond the standard interface.
    data = {**jinni.capabilities(), "interface_extras": interface_extras(jinni)}
    return CapabilitiesResponse(**data)
