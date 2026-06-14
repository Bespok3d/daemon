from hypothesis import given
from hypothesis import strategies as st

from core.live import print_state

state_st = st.text() | st.sampled_from(["printing", "paused", "standby", "complete", "error"])

json_st = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(max_size=8),
    lambda children: st.lists(children, max_size=3)
    | st.dictionaries(st.text(max_size=5), children, max_size=3),
    max_leaves=12,
)


@given(state_st)
def test_subscribe_shape_maps_state(state: str) -> None:
    payload = {"result": {"status": {"print_stats": {"state": state}}}}
    expected = {"active": state in print_state.PRINTING_STATES, "state": state}
    assert print_state.print_state_event(payload) == expected


@given(state_st)
def test_notify_shape_maps_state(state: str) -> None:
    payload = {
        "method": print_state.STATUS_NOTIFY_METHOD,
        "params": [{"print_stats": {"state": state}}],
    }
    expected = {"active": state in print_state.PRINTING_STATES, "state": state}
    assert print_state.print_state_event(payload) == expected


@given(st.dictionaries(st.text(max_size=8), json_st, max_size=6))
def test_arbitrary_payload_never_crashes_and_keeps_shape(payload: dict) -> None:
    result = print_state.print_state_event(payload)
    if result is not None:
        assert result["active"] == (result["state"] in print_state.PRINTING_STATES)
