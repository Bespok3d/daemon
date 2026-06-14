"""Load the Jinni the adapter shipped, or fall back to generic.

An adapter installs its jinni as a module named `bespok3d_jinni` next to the daemon (on the python
path) exposing a `make_jinni()` factory. When no adapter jinni is present (unknown target, or dev),
the generic jinni keeps the daemon up: it knows bespok3d's own core layout but not any target's.

Permissive input, strict output: an adapter may ship a minimal jinni, but whatever it ships, the
core path variables must resolve, and a klipper printer jinni must expose the klipper path contract.
The gate below enforces that, so a misconfigured adapter fails loudly at load instead of producing a
broken install later.
"""
from jinni import CORE_PATH_KEYS, KLIPPER_PATH_KEYS, Jinni, KlipperPrinterJinni


class GenericJinni(Jinni):
    id = "generic"


def _missing_keys(paths: dict[str, str], required: frozenset[str]) -> list[str]:
    return sorted(key for key in required if not paths.get(key))


_REQUIRED_KLIPPER_RESTARTS = ("klipper", "moonraker")


def _verify_contract(jinni: Jinni) -> None:
    paths = jinni.paths()
    missing_core = _missing_keys(paths, CORE_PATH_KEYS)
    if missing_core:
        raise ValueError(f"jinni is missing core path variables: {missing_core}")
    if not isinstance(jinni, KlipperPrinterJinni):
        return
    missing_klipper = _missing_keys(paths, KLIPPER_PATH_KEYS)
    if missing_klipper:
        raise ValueError(f"klipper jinni is missing klipper path variables: {missing_klipper}")
    missing_restarts = [
        hook for hook in _REQUIRED_KLIPPER_RESTARTS if not jinni.restart_command(hook)
    ]
    if missing_restarts:
        raise ValueError(f"klipper jinni is missing restart commands for: {missing_restarts}")


def get_jinni() -> Jinni:
    # The adapter installs its jinni next to the daemon. If none is present we stay generic; if one
    # is present it MUST implement the Jinni interface (the basic contract) and satisfy the path
    # contract for its tier; anything extra it offers rides along on the object for the daemon to
    # use when a capability flag advertises it.
    try:
        import bespok3d_jinni  # type: ignore[import-not-found]
    except ImportError:
        return GenericJinni()
    jinni = bespok3d_jinni.make_jinni()
    if not isinstance(jinni, Jinni):
        raise TypeError(
            f"the adapter's make_jinni() returned {type(jinni).__name__}, "
            "which does not implement the Jinni interface"
        )
    _verify_contract(jinni)
    return jinni
