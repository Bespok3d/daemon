"""The reported-facts facet of the jinni: the static target facts the daemon relays to the app.

Each is an overridable stub the base tier answers with a neutral default ("unknown", empty), so a
generic box reports nothing surprising; a device jinni overrides the ones it knows. The base Jinni
assembles these into `capabilities()`; the live readings come from the probing facet.
"""
import subprocess

_KLIPPER_VERSION_TIMEOUT_S = 3


class Facts:
    def hardware(self) -> list[str]:
        return []

    def firmware_version(self) -> str:
        return "unknown"

    def version(self) -> str:
        """The adapter jinni's own version (its daemon-side half), distinct from the daemon."""
        return "unknown"

    def preferred_registries(self) -> list[str]:
        return []

    def capability_flags(self) -> set[str]:
        return set()


class KlipperFacts(Facts):
    """The klipper-only fact a klipper printer adds: the running Klipper version."""

    def klipper_version(self) -> str:
        try:
            result = subprocess.run(
                ["python3", "-c", "import klippy; print(klippy.VERSION)"],
                capture_output=True, text=True, timeout=_KLIPPER_VERSION_TIMEOUT_S, check=False,
            )
            return result.stdout.strip() or "unknown"
        except Exception:
            return "unknown"
