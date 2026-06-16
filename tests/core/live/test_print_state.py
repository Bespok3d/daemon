from core.live import print_state

# The daemon relays blocked-action tokens opaquely; these stand in for any jinni's vocabulary.
RESTART_DISPLAY = "restart-display"
RESTART_KLIPPER = "restart-klipper"
RESTART_MOONRAKER = "restart-moonraker"


def test_app_frame_sorts_the_blocked_tokens() -> None:
    frame = print_state.app_frame(frozenset({RESTART_MOONRAKER, RESTART_KLIPPER, RESTART_DISPLAY}))
    assert frame == {"blocked_actions": [RESTART_DISPLAY, RESTART_KLIPPER, RESTART_MOONRAKER]}


def test_app_frame_is_empty_when_nothing_blocked() -> None:
    assert print_state.app_frame(frozenset()) == {"blocked_actions": []}
