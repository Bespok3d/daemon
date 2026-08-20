# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The socket under the daemon-to-jinni protocol, against a real Unix socket.

This is the layer every plugin op crosses on the printer. What it must never do is hand the daemon
half an answer: a jinni killed mid reply (OOM on the 512MB board, a service restart under it) leaves
bytes that still parse as JSON and read as a genuine verdict. These tests run a real listener that
misbehaves in each of those ways.
"""
import asyncio
import contextlib
import shutil
import socket
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from protocol import frame

_A_WHOLE_REPLY = b'{"ok": true, "result": "the printer answered"}' + frame.ETX
_A_REPLY_CUT_SHORT = b'{"ok": true, "result": "the printer answ'


def _reply_complete(buffer: bytes) -> bool:
    return buffer.endswith(frame.ETX)


@pytest.fixture
def socket_dir() -> Iterator[Path]:
    """A short-pathed home for the socket: a Unix socket path has an OS length limit that the test
    runner's own temp directory names can exceed."""
    made = Path(tempfile.mkdtemp(prefix="b3sock-"))
    yield made
    shutil.rmtree(made, ignore_errors=True)


@pytest.fixture
def unserved_socket_path(socket_dir: Path) -> str:
    """A path where no jinni is listening: the child is down, restarting, or was never started."""
    return str(socket_dir / "jinni.sock")


@pytest.fixture
def jinni_saying(request: pytest.FixtureRequest, socket_dir: Path) -> Iterator[str]:
    """A listener that sends the parametrized bytes to one caller, then closes the connection."""
    socket_path = str(socket_dir / "jinni.sock")
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(socket_path)
    listener.listen(1)

    def serve_one_caller() -> None:
        connection, _ = listener.accept()
        with connection:
            connection.recv(4096)
            connection.sendall(request.param)

    server = threading.Thread(target=serve_one_caller, daemon=True)
    server.start()
    yield socket_path
    server.join(timeout=2)
    listener.close()


@pytest.mark.parametrize("jinni_saying", [_A_WHOLE_REPLY], indirect=True)
def test_a_whole_reply_reaches_the_daemon(jinni_saying: str) -> None:
    assert frame.exchange(jinni_saying, b"ask" + frame.ETX, _reply_complete) == _A_WHOLE_REPLY


@pytest.mark.parametrize("jinni_saying", [_A_REPLY_CUT_SHORT], indirect=True)
def test_a_jinni_killed_mid_reply_is_no_answer_at_all(jinni_saying: str) -> None:
    """Half a reply still parses as JSON, so the only safe reading is that nothing came back."""
    assert frame.exchange(jinni_saying, b"ask" + frame.ETX, _reply_complete) is None


def test_a_jinni_that_is_not_running_is_no_answer_at_all(unserved_socket_path: str) -> None:
    assert frame.exchange(unserved_socket_path, b"ask" + frame.ETX, _reply_complete) is None


def test_a_reply_that_never_ends_is_cut_off_instead_of_filling_the_printers_memory(
    monkeypatch: pytest.MonkeyPatch, socket_dir: Path,
) -> None:
    """The board has 512MB and no swap for this. A jinni that never terminates its frame has to hit
    a ceiling, or the daemon grows until the kernel kills something the user was using."""
    monkeypatch.setattr(frame, "MAX_FRAME_BYTES", 32)
    socket_path = str(socket_dir / "jinni.sock")
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(socket_path)
    listener.listen(1)
    keep_talking = threading.Event()

    def never_finish_the_frame() -> None:
        connection, _ = listener.accept()
        with connection, contextlib.suppress(BrokenPipeError):
            connection.recv(4096)
            while not keep_talking.is_set():
                connection.sendall(b"x" * 16)

    server = threading.Thread(target=never_finish_the_frame, daemon=True)
    server.start()

    assert frame.exchange(socket_path, b"ask" + frame.ETX, _reply_complete) is None

    keep_talking.set()
    server.join(timeout=2)
    listener.close()


async def _pushing(socket_path: str, frames: list[bytes]) -> asyncio.AbstractServer:
    """A jinni holding the connection open and pushing frames, the way the print-state feed does."""
    async def push(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.read(64)
        for pushed in frames:
            writer.write(pushed)
        await writer.drain()
        writer.close()
    return await asyncio.start_unix_server(push, path=socket_path)


async def test_every_pushed_frame_reaches_the_daemon_in_order(socket_dir: Path) -> None:
    socket_path = str(socket_dir / "jinni.sock")
    pushed = [b'{"ok": true, "result": []}' + frame.ETX,
              b'{"ok": true, "result": ["printing"]}' + frame.ETX]
    server = await _pushing(socket_path, pushed)

    received = [received async for received in frame.stream(socket_path, b"subscribe")]

    assert received == pushed
    server.close()


async def test_a_stream_ends_when_the_jinni_closes_rather_than_waiting_forever(
    socket_dir: Path,
) -> None:
    """The app's print lock relays this feed. It has to end when the jinni goes, so the app can
    reconnect to the new one instead of holding a feed that will never speak again."""
    socket_path = str(socket_dir / "jinni.sock")
    server = await _pushing(socket_path, [b'{"ok": true, "result": []}'])

    received = [received async for received in frame.stream(socket_path, b"subscribe")]

    assert received == []
    server.close()
