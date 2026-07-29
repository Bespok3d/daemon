# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
from hypothesis import given
from hypothesis import strategies as st

from core.live import print_state

token_st = st.frozensets(st.text(max_size=16), max_size=6)


@given(token_st)
def test_app_frame_is_the_sorted_token_list(tokens: frozenset[str]) -> None:
    frame = print_state.app_frame(tokens)
    assert frame == {"blocked_actions": sorted(tokens)}
    assert frame["blocked_actions"] == sorted(frame["blocked_actions"])
