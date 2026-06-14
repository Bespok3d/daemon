"""The Jinni interface: the contract the generic daemon orders a target-specific adapter against.

The daemon owns everything inside the bespok3d filesystem and never knows a specific target. Every
adapter ships a Jinni (its daemon-side half), installed next to the daemon and loaded at runtime,
that REALIZES the host-crossing operations and reports the target's facts.

Three tiers, one per room:
- `Jinni` (`base.py`): a generic linux box, guaranteeing the core path variables by construction.
- `KlipperPrinterJinni` (`klipper.py`): the klipper path contract plus the klipper-only facts.
- the device jinni (shipped by the adapter) extends `KlipperPrinterJinni` and supplies its own paths
  and hardware specifics.

`inspection.py` holds the generic device probes both tiers surface. This package file is the facade
the daemon imports: the two tiers, their path-key contracts, and `interface_extras`.
"""
from .base import CORE_PATH_KEYS, Jinni
from .klipper import KLIPPER_PATH_KEYS, KlipperPrinterJinni

__all__ = [
    "CORE_PATH_KEYS",
    "KLIPPER_PATH_KEYS",
    "Jinni",
    "KlipperPrinterJinni",
    "interface_extras",
]


def interface_extras(jinni: Jinni) -> list[str]:
    """Public names a jinni exposes beyond the bespok3d jinni interface (the Jinni and
    KlipperPrinterJinni tiers). Computed by the DAEMON over the loaded object, not self-reported, so
    an adapter cannot hide the fact that it ships behaviour the daemon does not define. Non-empty is
    surfaced to the user as a caution.
    """
    defined = set(dir(Jinni)) | set(dir(KlipperPrinterJinni))
    return sorted(
        name for name in dir(type(jinni))
        if not name.startswith("_") and name not in defined
    )
