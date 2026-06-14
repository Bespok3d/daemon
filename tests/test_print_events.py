import json

from core import print_events


def notify(status: dict) -> dict:
    return {"method": "notify_status_update", "params": [status, 1.0]}


def test_subscribe_message_targets_print_stats_state() -> None:
    msg = json.loads(print_events.subscribe_message(7))
    assert msg["method"] == "printer.objects.subscribe"
    assert msg["params"]["objects"] == {"print_stats": ["state"]}
    assert msg["id"] == 7


def test_print_state_event_from_status_notification_printing() -> None:
    event = print_events.print_state_event(notify({"print_stats": {"state": "printing"}}))
    assert event == {"active": True, "state": "printing"}


def test_print_state_event_paused_is_active() -> None:
    event = print_events.print_state_event(notify({"print_stats": {"state": "paused"}}))
    assert event == {"active": True, "state": "paused"}


def test_print_state_event_from_subscribe_result_idle() -> None:
    payload = {"result": {"status": {"print_stats": {"state": "standby"}}}, "id": 1}
    assert print_events.print_state_event(payload) == {"active": False, "state": "standby"}


def test_print_state_event_none_when_no_print_stats() -> None:
    # a status update for a different object carries no print_stats
    assert print_events.print_state_event(notify({"toolhead": {"position": [0, 0, 0]}})) is None


def test_print_state_event_none_for_unrelated_message() -> None:
    assert print_events.print_state_event({"method": "notify_klippy_ready", "params": []}) is None
