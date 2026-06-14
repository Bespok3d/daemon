"""The 0x03-framed JSON-over-Unix-socket protocol shared by the printer's Klipper and Moonraker API
sockets: encode a request and run one request/response exchange. Each client decodes the reply its
own way (Klipper wants the first frame; Moonraker reads past interleaved notifications), so decoding
stays with the client; only the wire framing and the socket round-trip live here.
"""
import json
import socket
from collections.abc import Callable

ETX = b"\x03"
DEFAULT_TIMEOUT_S = 3.0
_RECV_CHUNK = 4096


def encode(payload: dict) -> bytes:
    return json.dumps(payload).encode() + ETX


def exchange(socket_path: str, request: bytes, reply_complete: Callable[[bytes], bool],
             timeout: float = DEFAULT_TIMEOUT_S) -> bytes | None:
    """Open the API socket, send one request, accumulate the reply until `reply_complete(buffer)` or
    the peer closes. None when the socket is unreachable (the service is down, restarting, or absent
    on this host)."""
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
                if reply_complete(buffer):
                    break
    except OSError:
        return None
    return buffer
