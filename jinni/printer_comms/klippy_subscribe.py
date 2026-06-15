"""Subscribe to Klipper's print_stats over its auth-free API socket, push-style (ADR-0037).

The one-shot reads live in `klippy`; this is the long-lived watch the jinni keeps so it can stream
the blocked-action set to the daemon on change instead of polling. It opens one persistent async
connection to Klipper's API socket, subscribes to `print_stats.state`, and yields each observed
state. Klipper's API socket has NO auth, so this survives the moonraker-auth plugin's force_logins.

Pure framing/parsing here is unit-tested; the IO shell reconnects when Klipper restarts (a plugin op
bouncing it, an OTA), yielding "" in the gap so a stale "printing" never sticks while the socket is
down. The caller maps a state to the blocked set and dedupes, so a churn of equal states is cheap.
"""
import asyncio
import json
from collections.abc import AsyncIterator

from .frame import ETX, encode

_RECONNECT_DELAY_S = 2.0
_DISCONNECTED_STATE = ""

# Subscribe to print_stats.state. response_template is echoed on each status update; left empty,
# Klipper sends updates as bare {"params": {"status": {...}, "eventtime": ...}} frames.
_SUBSCRIBE = {
    "id": 1,
    "method": "objects/subscribe",
    "params": {"objects": {"print_stats": ["state"]}, "response_template": {}},
}


def subscribe_request() -> bytes:
    return encode(_SUBSCRIBE)


def _state_in_block(block: object) -> str | None:
    status = block.get("status") if isinstance(block, dict) else None
    print_stats = status.get("print_stats") if isinstance(status, dict) else None
    state = print_stats.get("state") if isinstance(print_stats, dict) else None
    return state if isinstance(state, str) else None


def state_from_frame(message: dict) -> str | None:
    """The print_stats.state in one API-socket frame, or None if it carries none. The subscribe
    reply nests status under `result`; later status updates nest it under `params`."""
    for block in (message.get("result"), message.get("params")):
        state = _state_in_block(block)
        if state is not None:
            return state
    return None


async def _read_states(socket_path: str) -> AsyncIterator[str]:
    """One connection: subscribe, then yield each print_stats.state the socket reports until it
    closes. Raises OSError if the socket is unreachable, so the watcher can reconnect."""
    reader, writer = await asyncio.open_unix_connection(socket_path)
    try:
        writer.write(subscribe_request())
        await writer.drain()
        while True:
            raw = await reader.readuntil(ETX)
            state = state_from_frame(json.loads(raw.rstrip(ETX).decode(errors="replace")))
            if state is not None:
                yield state
    finally:
        writer.close()


async def watch_print_state(socket_path: str) -> AsyncIterator[str]:
    """Klipper's print_stats.state, pushed on change, reconnecting forever. Yields "" whenever the
    socket is down so a consumer never holds a stale active state across a Klipper restart."""
    while True:
        try:
            async for state in _read_states(socket_path):
                yield state
        except (OSError, asyncio.IncompleteReadError, ValueError):
            pass
        yield _DISCONNECTED_STATE
        await asyncio.sleep(_RECONNECT_DELAY_S)
