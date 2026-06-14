"""Talk to Moonraker over its Unix domain socket (comms/moonraker.sock).

Local IPC that never needs auth (Moonraker's docs say so, and OctoEverywhere's client relies on it),
so it reads /server/info's failed_components and warnings even when the moonraker-auth plugin sets
force_logins and shuts the HTTP API. Protocol: JSON-RPC 2.0 frames terminated by 0x03. Moonraker
interleaves id-less async notifications with replies, so we read frames until our request id shows.
"""
import json

from .frame import ETX, encode, exchange

_REQUEST_ID = 7700  # any int; matched in the reply to skip interleaved notifications


def encode_rpc(method: str, request_id: int = _REQUEST_ID) -> bytes:
    return encode({"jsonrpc": "2.0", "method": method, "id": request_id})


def decode_frames(blob: bytes) -> list[dict]:
    """Every complete 0x03-delimited JSON object in blob (malformed or partial pieces skipped)."""
    frames: list[dict] = []
    for piece in blob.split(ETX):
        if not piece:
            continue
        try:
            decoded = json.loads(piece.decode(errors="replace"))
        except ValueError:
            continue
        if isinstance(decoded, dict):
            frames.append(decoded)
    return frames


def result_for_id(frames: list[dict], request_id: int = _REQUEST_ID) -> dict:
    """The `result` of the reply carrying our id; {} if absent or an error reply. Moonraker also
    pushes id-less status notifications over the socket, which this skips."""
    for frame in frames:
        result = frame.get("result")
        if frame.get("id") == request_id and isinstance(result, dict):
            return result
    return {}


def _reply_present(buffer: bytes, request_id: int) -> bool:
    return any(frame.get("id") == request_id for frame in decode_frames(buffer.rpartition(ETX)[0]))


def server_info(socket_path: str, request_id: int = _REQUEST_ID) -> dict | None:
    """Moonraker's server.info result (klippy_state / failed_components / warnings ...), or None if
    the socket is unreachable; {} when it answered without a usable result."""
    request = encode_rpc("server.info", request_id)
    buffer = exchange(socket_path, request, lambda reply: _reply_present(reply, request_id))
    if buffer is None:
        return None
    return result_for_id(decode_frames(buffer.rpartition(ETX)[0]), request_id)
