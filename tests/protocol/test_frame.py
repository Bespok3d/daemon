# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The 0x03-framed socket transport (frame.py) and the contract shapes it carries (contracts.py),
under a truncated, an oversized, and a malformed reply from the jinni side of the socket.

The wire is delimiter-framed (an ETX terminator), not length-prefixed, so there is no "bad length
header" shape to exercise here; the malformed cases covered instead are a non-JSON body and a
JSON body that does not match the requested verb's contract shape.
"""
import json
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

import protocol
from protocol import frame


def _frame_is_complete(buffer: bytes) -> bool:
    return buffer.endswith(frame.ETX)


@pytest.fixture
def socket_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A short, relative socket filename inside tmp_path. AF_UNIX caps sun_path around 104 bytes on
    macOS, and pytest's own tmp_path nesting alone already exceeds that, so the process cwd is
    pinned to tmp_path and the socket is addressed by its short relative name instead."""
    monkeypatch.chdir(tmp_path)
    return "jinni.sock"


def _answer_one_caller(listener: socket.socket, scripted_reply: bytes) -> None:
    """Take the one connection the test makes, write the scripted bytes at it, and hang up."""
    connection, _ = listener.accept()
    try:
        connection.sendall(scripted_reply)
    except BrokenPipeError:
        pass  # cutting an over-long frame off mid write is the behaviour under test
    finally:
        connection.close()


@contextmanager
def _scripted_jinni(socket_path: str, scripted_reply: bytes) -> Iterator[None]:
    """Stand in for the jinni process on the other end of the socket: accept exactly one
    connection, write the scripted bytes, then close, the way a broken peer would."""
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(socket_path)
    listener.listen(1)
    server_thread = threading.Thread(
        target=_answer_one_caller, args=(listener, scripted_reply), daemon=True,
    )
    server_thread.start()
    try:
        yield
    finally:
        server_thread.join(timeout=5.0)
        listener.close()


def test_exchange_refuses_a_reply_truncated_before_the_etx_terminator(socket_path: str) -> None:
    """The peer closes right after writing a body that already happens to be valid JSON, but never
    sends the ETX terminator. exchange() must not hand this back as if it were a complete frame."""
    scripted_reply = b'{"ok": true, "result": null}'
    with _scripted_jinni(socket_path, scripted_reply):
        received = frame.exchange(
            socket_path, b"irrelevant-request", _frame_is_complete, timeout=5.0,
        )
    assert received is None, (
        "a reply whose connection closed before the ETX terminator must be refused as None, not "
        "handed to the caller looking like a complete, trustworthy frame"
    )


def test_exchange_refuses_a_reply_larger_than_max_frame_bytes(
    socket_path: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The peer writes far more than the declared frame ceiling and never terminates it. exchange()
    must stop and refuse rather than accumulate the whole thing into memory."""
    ceiling = 8192
    monkeypatch.setattr(frame, "MAX_FRAME_BYTES", ceiling)
    oversized_body = b"x" * (ceiling * 4)
    with _scripted_jinni(socket_path, oversized_body):
        received = frame.exchange(
            socket_path, b"irrelevant-request", _frame_is_complete, timeout=5.0,
        )
    assert received is None, (
        f"a reply that grew past the {ceiling}-byte ceiling must be refused as None instead of "
        "accumulated in full"
    )


def test_wire_call_refuses_a_non_json_reply_body(socket_path: str) -> None:
    """A syntactically malformed body, correctly ETX-terminated, must surface as the daemon's own
    ProtocolError, never an uncaught decode exception."""
    malformed_reply = b"not-json-at-all" + frame.ETX
    with _scripted_jinni(socket_path, malformed_reply):
        with pytest.raises(protocol.ProtocolError):
            protocol.call(socket_path, "health", [], timeout=5.0)


def test_wire_call_refuses_a_reply_whose_shape_does_not_match_the_verb_contract(
    socket_path: str,
) -> None:
    """Valid JSON, correctly framed, reporting ok, but missing the fields the "health" verb's
    contract shape (DeviceHealth, built from contracts.py) requires. This must refuse the same way
    a non-JSON body does, never leak the decoder's own KeyError past the protocol boundary."""
    wrong_shape_reply = json.dumps({"ok": True, "result": {"unexpected": "shape"}}).encode() + frame.ETX  # noqa: E501
    with _scripted_jinni(socket_path, wrong_shape_reply):
        with pytest.raises(protocol.ProtocolError):
            protocol.call(socket_path, "health", [], timeout=5.0)
