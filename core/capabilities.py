"""
Capabilities: what this printer can do.

The daemon just consumes them: it asks the jinni (through the seam) for the target's facts.
"""

from api.schemas import CapabilitiesResponse
from core import jinni_client


def get_capabilities() -> CapabilitiesResponse:
    return CapabilitiesResponse(**jinni_client.capabilities_report())
