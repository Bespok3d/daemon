"""Shape the jinni's blocked-action token set into the daemon's /ws/print-state frame.

The daemon does not touch the printer or classify a print state (ADR-0037): the jinni pushes the
blocked-action set, the daemon relays it. This is the single source for the app-facing frame shape,
kept pure so the relay route stays a dumb forwarder.
"""


def app_frame(blocked_actions: frozenset[str]) -> dict:
    """The /ws/print-state frame the app receives: the sorted blocked-action tokens (empty list =
    nothing blocked, so the UI is unlocked). The app maps each token to a localized string."""
    return {"blocked_actions": sorted(blocked_actions)}
