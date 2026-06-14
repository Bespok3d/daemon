"""Talk to Klipper's API server over its Unix domain socket.

This is local IPC with NO authentication, so it keeps working when Moonraker has `force_logins` on
(the moonraker-auth plugin) and shuts its HTTP API in the daemon's face. Protocol (Klipper's
docs/API_Server.md + webhooks.py): JSON request/response dicts terminated by an ASCII 0x03 byte.
"""
import json
import socket

_ETX = b"\x03"
_RECV_CHUNK = 4096
_DEFAULT_TIMEOUT_S = 3.0
_PRINT_STATS_QUERY = {"objects": {"print_stats": None}}


def encode_request(method: str, params: dict, request_id: int = 1) -> bytes:
    return json.dumps({"id": request_id, "method": method, "params": params}).encode() + _ETX


def decode_frame(buffer: bytes) -> dict:
    """Parse the first complete 0x03-terminated JSON frame; {} if none present or it is bad."""
    frame, terminator, _rest = buffer.partition(_ETX)
    if not terminator:
        return {}
    try:
        decoded = json.loads(frame.decode(errors="replace"))
    except ValueError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def print_state_from_query(response: dict) -> str:
    status = response.get("result", {}).get("status", {})
    return str(status.get("print_stats", {}).get("state", ""))


def klippy_state_from_info(response: dict) -> str:
    return str(response.get("result", {}).get("state", ""))


def _request(socket_path: str, method: str, params: dict,
             timeout: float = _DEFAULT_TIMEOUT_S) -> dict | None:
    """Send one request to the API socket and return the parsed response, or None when the socket is
    unreachable (Klipper down / restarting, or no socket on this host)."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(socket_path)
            sock.sendall(encode_request(method, params))
            buffer = b""
            while _ETX not in buffer:
                chunk = sock.recv(_RECV_CHUNK)
                if not chunk:
                    break
                buffer += chunk
    except OSError:
        return None
    return decode_frame(buffer)


def query_print_state(socket_path: str) -> str | None:
    """Klipper's print_stats.state via the API socket; None when the socket is unreachable."""
    response = _request(socket_path, "objects/query", _PRINT_STATS_QUERY)
    return None if response is None else print_state_from_query(response)


def query_klippy_state(socket_path: str) -> str | None:
    """Klipper's readiness ('ready' / 'startup' / ...) via the API socket; None when unreachable."""
    response = _request(socket_path, "info", {})
    return None if response is None else klippy_state_from_info(response)
