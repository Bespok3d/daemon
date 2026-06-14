"""Pure helpers for the Moonraker print_stats websocket bridge (no IO, unit-tested).

The daemon's /ws/print-state route opens a websocket to Moonraker, subscribes to print_stats, and
relays state changes to the app. The JSON-RPC message shapes and the active/state derivation live
here so the bridge logic is testable without a live socket.
"""
import json

PRINTING_STATES = ("printing", "paused")
SUBSCRIBE_METHOD = "printer.objects.subscribe"
STATUS_NOTIFY_METHOD = "notify_status_update"


def subscribe_message(request_id: int = 1) -> str:
    """The JSON-RPC request that subscribes to print_stats.state."""
    return json.dumps({
        "jsonrpc": "2.0",
        "method": SUBSCRIBE_METHOD,
        "params": {"objects": {"print_stats": ["state"]}},
        "id": request_id,
    })


def _status_block(payload: dict) -> dict:
    """The status block ({print_stats: ...}) from a subscribe result or a status notification."""
    result = payload.get("result")
    status = result.get("status") if isinstance(result, dict) else None
    if isinstance(status, dict):
        return status
    params = payload.get("params")
    if payload.get("method") == STATUS_NOTIFY_METHOD and isinstance(params, list) \
            and params and isinstance(params[0], dict):
        return params[0]
    return {}


def print_state_event(payload: dict) -> dict | None:
    """Map a Moonraker message to {active, state}, or None if it carries no print_stats.state."""
    print_stats = _status_block(payload).get("print_stats")
    if not isinstance(print_stats, dict) or not isinstance(print_stats.get("state"), str):
        return None
    state = print_stats["state"]
    return {"active": state in PRINTING_STATES, "state": state}
