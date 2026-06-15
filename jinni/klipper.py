"""The klipper-printer Jinni tier: composes the klipper concern facets over the generic base.

A klipper printer overrides realization (its config / extra / component placement classes), facts
(the running Klipper version), and probing (the live print state plus the mid-print permission
gate), and adds per-service health verdicts; each override lives in its concern's facet
(jinni/realization.py, facts.py, probing.py, health.py), exactly as the base tier is faceted. This
tier wires those facets onto the base Jinni, carries the klipper path-variable contract as a class
attr, and assembles the klipper-extended reports (the only cross-facet work, kept on the composition
root where `self` is the fully-typed jinni). A device adapter extends it and supplies only its own
paths and hardware specifics.
"""
from collections.abc import AsyncIterator

from . import inspection
from .base import Jinni
from .contracts import RESTART_DISPLAY, RESTART_KLIPPER, RESTART_MOONRAKER
from .facts import KlipperFacts
from .health import KlipperHealth
from .layout import KLIPPER_PATH_KEYS
from .printer_comms import klippy_subscribe
from .probing import KlipperProbing
from .realization import KlipperRealization


class KlipperPrinterJinni(KlipperRealization, KlipperFacts, KlipperProbing, KlipperHealth, Jinni):
    KLIPPER_PATH_KEYS = KLIPPER_PATH_KEYS

    def diagnose(self) -> dict:
        return {**super().diagnose(), "moonraker": self.port_listening(inspection.MOONRAKER_PORT)}

    def capabilities(self) -> dict:
        return {**super().capabilities(), "klipper_version": self.klipper_version()}

    def blocked_actions(self) -> frozenset[str]:
        """The action tokens a running print forbids right now, read live. Cross-facet (print state
        from probing, the display token from realization), so it sits on the composition root where
        `self` is the fully-typed jinni."""
        _active, state = self.print_active()
        return self._blocked_for_state(state)

    async def watch_blocked_actions(self) -> AsyncIterator[frozenset[str]]:
        """Push the blocked-action set on change, subscribing to Klipper's print_stats (auth-immune)
        so the daemon's feed never polls. Dedupes by token set: distinct states that forbid the same
        actions emit nothing new."""
        last: frozenset[str] | None = None
        async for state in klippy_subscribe.watch_print_state(self.paths().get("KLIPPER_UDS", "")):
            blocked = self._blocked_for_state(state)
            if blocked != last:
                last = blocked
                yield blocked

    def _blocked_for_state(self, state: str) -> frozenset[str]:
        if not self.is_active_print_state(state):
            return frozenset()
        tokens = {RESTART_KLIPPER, RESTART_MOONRAKER}
        if self.display_service_tokens():
            tokens.add(RESTART_DISPLAY)
        return frozenset(tokens)
