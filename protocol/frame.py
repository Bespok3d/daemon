# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The 0x03-framed JSON-over-Unix-socket protocol shared by the printer's Klipper and Moonraker API
sockets: encode a request and run one request/response exchange. Each client decodes the reply its
own way (Klipper wants the first frame; Moonraker reads past interleaved notifications), so decoding
stays with the client; only the wire framing and the socket round-trip live here.
"""
import asyncio
import json
import socket
from collections.abc import AsyncIterator, Callable

ETX = b"\x03"
DEFAULT_TIMEOUT_S = 3.0
_RECV_CHUNK = 4096

# The asyncio StreamReader buffer cap for a single framed message. The default (64 KiB) is far too
# small for the write_files verb, whose request carries whole device files (a patched Klipper
# source, several at once on a restore): a larger frame overran readuntil with LimitOverrunError,
# which the jinni swallowed by closing the connection unanswered ("no reply for write_files").
# Generous headroom over any realistic source/config file, bounding memory.
MAX_FRAME_BYTES = 16 * 1024 * 1024


def encode(payload: dict) -> bytes:
    return json.dumps(payload).encode() + ETX


def exchange(socket_path: str, request: bytes, reply_complete: Callable[[bytes], bool],
             timeout: float = DEFAULT_TIMEOUT_S) -> bytes | None:
    """Open the API socket, send one request, and hand back the reply once `reply_complete(buffer)`
    says it is whole. None when the socket is unreachable (the service is down, restarting, or
    absent on this host) and None when the reply never completed, which the caller treats the
    same way: no usable answer came back."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(socket_path)
            sock.sendall(request)
            return _whole_reply(sock, reply_complete)
    except OSError:
        return None


def _whole_reply(sock: socket.socket, reply_complete: Callable[[bytes], bool]) -> bytes | None:
    """The reply read off the socket, or None when no whole one arrived.

    A peer that dies mid frame leaves bytes that can still parse as valid JSON and read as a genuine
    result, so a reply that stops short of its terminator is refused rather than handed on. A peer
    that never terminates its frame is cut off at MAX_FRAME_BYTES, which is what makes that ceiling
    the memory bound it claims to be."""
    buffer = b""
    while len(buffer) <= MAX_FRAME_BYTES:
        chunk = sock.recv(_RECV_CHUNK)
        if not chunk:
            return None
        buffer += chunk
        if reply_complete(buffer):
            return buffer
    return None


async def stream(socket_path: str, request: bytes) -> AsyncIterator[bytes]:
    """Open the socket, send one request, then yield each ETX-framed reply as it arrives, until the
    peer closes (a streaming verb: the jinni keeps the connection open and pushes frames). A peer
    that ends the stream, or dies part way through a frame, ends the loop rather than blocking on a
    reply that is never coming. A socket nothing is listening on raises out of the first line, so
    the caller ends its feed instead of relaying one that will never speak."""
    reader, writer = await asyncio.open_unix_connection(socket_path)
    try:
        writer.write(request)
        await writer.drain()
        while True:
            yield await reader.readuntil(ETX)
    except (OSError, asyncio.IncompleteReadError):
        return
    finally:
        writer.close()
