"""The wire protocol between the daemon and the jinni process (ADR-0037).

The daemon and the jinni run as two processes; this is the data contract over the 0x03-framed JSON
transport (`printer_comms/frame`). The daemon sends one verb call; the jinni answers with the verb's
serializable result or an error. Both sides import THIS one module, so the wire shape is
single-source and cannot drift. A versioned handshake (`hello`) refuses an incompatible peer with a
clear "update the adapter" path instead of misbehaving.

Request frame:  {"v": <int>, "verb": <str>, "args": [<json>, ...]}
Result frame:   {"ok": true, "result": <json>}  |  {"ok": false, "error": <str>}

Only the verbs in CONTRACT_VERBS are callable, so a peer can never reach an arbitrary jinni method.
The dataclass shapes (DeviceHealth, CommandEffect) are encoded with `asdict` and decoded per verb on
the receiving side; `blocked_actions` is a token set, sent as a sorted list. The streaming verb
`subscribe-blocked-actions` keeps the connection open and pushes a token-set frame on each change.
"""
import json
from collections.abc import AsyncIterator
from dataclasses import asdict, is_dataclass
from typing import Any

from . import frame
from .decode import decode_result

PROTOCOL_VERSION = 3
HELLO = "hello"

# The streaming verb: instead of one reply, the jinni keeps the connection open and pushes a frame
# (the current blocked-action token set) whenever it changes. Handled apart from the one-shot verbs.
SUBSCRIBE_BLOCKED_ACTIONS = "subscribe-blocked-actions"

# The closed set of verbs a daemon may call on the jinni. `hello` is the handshake; the rest map to
# methods of the same name on the loaded jinni. A verb outside this set is refused.
CONTRACT_VERBS = frozenset({
    HELLO, SUBSCRIBE_BLOCKED_ACTIONS,
    "paths", "capabilities_report", "capability_flags",
    "placement_destination", "instrument_destination", "restart_command", "render_service_script",
    "classify_commands", "health", "blocked_actions",
    "run_actions", "wire", "unwire",
    "prune_dead_config_links", "remove_bespok3d_includes", "prune_bespok3d_config_dir",
    "fetch", "write_files",
})


class ProtocolError(Exception):
    """A torn frame, an unknown or refused verb, or a peer on an incompatible protocol version."""


def _to_json(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if isinstance(value, (list, tuple)):
        return [_to_json(item) for item in value]
    return value


def request_bytes(verb: str, args: list[Any]) -> bytes:
    return frame.encode({"v": PROTOCOL_VERSION, "verb": verb, "args": args})


def reply_complete(buffer: bytes) -> bool:
    return buffer.endswith(frame.ETX)


def parse_request(raw: bytes) -> tuple[str, list[Any]]:
    """Read one request frame. Raises ProtocolError on a torn frame, a version mismatch, or a verb
    outside the contract."""
    try:
        message = json.loads(raw.rstrip(frame.ETX).decode())
    except (ValueError, UnicodeDecodeError) as exc:
        raise ProtocolError(f"unreadable request frame: {exc}") from exc
    if message.get("v") != PROTOCOL_VERSION:
        raise ProtocolError(
            f"daemon speaks protocol v{PROTOCOL_VERSION}, peer sent v{message.get('v')}; "
            "update the adapter"
        )
    verb = message.get("verb")
    if verb not in CONTRACT_VERBS:
        raise ProtocolError(f"unknown verb: {verb!r}")
    return verb, list(message.get("args", []))


def result_bytes(result: Any) -> bytes:
    return frame.encode({"ok": True, "result": _to_json(result)})


def error_bytes(message: str) -> bytes:
    return frame.encode({"ok": False, "error": message})


def parse_result(verb: str, raw: bytes | None) -> Any:
    """Decode a reply frame into the verb's typed result. Raises ProtocolError when the jinni
    reported an error or the socket gave no reply (it died or was unreachable)."""
    if raw is None:
        raise ProtocolError(f"no reply from the jinni for {verb!r}")
    try:
        message = json.loads(raw.rstrip(frame.ETX).decode())
    except (ValueError, UnicodeDecodeError) as exc:
        raise ProtocolError(f"unreadable reply frame for {verb!r}: {exc}") from exc
    if not message.get("ok"):
        raise ProtocolError(message.get("error", "jinni reported an error"))
    return decode_result(verb, message.get("result"))


def call(socket_path: str, verb: str, args: list[Any], timeout: float = frame.DEFAULT_TIMEOUT_S) -> Any:  # noqa: E501
    """One request/response exchange with the jinni over the socket. Timeout-bounded; a dead or hung
    jinni surfaces as a ProtocolError the daemon can recycle on, never a block."""
    reply = frame.exchange(socket_path, request_bytes(verb, args), reply_complete, timeout)
    return parse_result(verb, reply)


async def stream(socket_path: str, verb: str, args: list[Any] | None = None) -> AsyncIterator[Any]:
    """Open a streaming verb and yield each pushed `result` as it arrives, until the jinni closes
    the stream. Raises ProtocolError on an error frame so the daemon can recycle the jinni."""
    async for raw in frame.stream(socket_path, request_bytes(verb, args or [])):
        message = json.loads(raw.rstrip(frame.ETX).decode())
        if not message.get("ok"):
            raise ProtocolError(message.get("error", "jinni reported an error"))
        yield message.get("result")
