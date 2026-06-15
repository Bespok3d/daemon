from core.live import print_state
from jinni.contracts import RESTART_DISPLAY, RESTART_KLIPPER, RESTART_MOONRAKER


def test_app_frame_sorts_the_blocked_tokens() -> None:
    frame = print_state.app_frame(frozenset({RESTART_MOONRAKER, RESTART_KLIPPER, RESTART_DISPLAY}))
    assert frame == {"blocked_actions": [RESTART_DISPLAY, RESTART_KLIPPER, RESTART_MOONRAKER]}


def test_app_frame_is_empty_when_nothing_blocked() -> None:
    assert print_state.app_frame(frozenset()) == {"blocked_actions": []}
