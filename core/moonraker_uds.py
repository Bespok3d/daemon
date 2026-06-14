"""Talk to Moonraker over its Unix domain socket (comms/moonraker.sock).

Local IPC that never needs auth (Moonraker's docs say so, and OctoEverywhere's client relies on it),
so it reads /server/info's failed_components and warnings even when the moonraker-auth plugin sets
force_logins and shuts the HTTP API. Protocol: JSON-RPC 2.0 frames terminated by 0x03. Moonraker
interleaves id-less async notifications with replies, so we read frames until our request id shows.
"""
import json
import socket

_ETX = b"\x03"
_RECV_CHUNK = 4096
_DEFAULT_TIMEOUT_S = 3.0
_REQUEST_ID = 7700  # any int; matched in the reply to skip interleaved notifications


def encode_rpc(method: str, request_id: int = _REQUEST_ID) -> bytes:
    return json.dumps({"jsonrpc": "2.0", "method": method, "id": request_id}).encode() + _ETX


def decode_frames(blob: bytes) -> list[dict]:
    """Every complete 0x03-delimited JSON object in blob (malformed or partial pieces skipped)."""
    frames: list[dict] = []
    for piece in blob.split(_ETX):
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
        if frame.get("id") == request_id and isinstance(frame.get("result"), dict):
            return frame["result"]
    return {}


def _exchange(socket_path: str, request: bytes, request_id: int,
              timeout: float = _DEFAULT_TIMEOUT_S) -> list[dict] | None:
    """Send one request, read frames until our reply lands; None when the socket is unreachable."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(socket_path)
            sock.sendall(request)
            buffer = b""
            while True:
                chunk = sock.recv(_RECV_CHUNK)
                if not chunk:
                    break
                buffer += chunk
                complete = decode_frames(buffer.rpartition(_ETX)[0])
                if any(frame.get("id") == request_id for frame in complete):
                    break
    except OSError:
        return None
    return decode_frames(buffer.rpartition(_ETX)[0])


def server_info(socket_path: str, request_id: int = _REQUEST_ID) -> dict | None:
    """Moonraker's server.info result (klippy_state / failed_components / warnings ...), or None if
    the socket is unreachable; {} when it answered without a usable result."""
    frames = _exchange(socket_path, encode_rpc("server.info", request_id), request_id)
    if frames is None:
        return None
    return result_for_id(frames, request_id)
