"""The Klipper print_stats subscription: pure framing/parsing, plus a live push over a fake sock."""
import asyncio
import json
import shutil
import tempfile
from collections.abc import Iterator

import pytest

from jinni.printer_comms import klippy_subscribe
from jinni.printer_comms.frame import ETX


@pytest.fixture
def socket_path() -> Iterator[str]:
    # A short dir: macOS caps an AF_UNIX path near 104 chars and pytest's tmp_path blows past it.
    directory = tempfile.mkdtemp(prefix="b3d", dir="/tmp")
    try:
        yield f"{directory}/k.sock"
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def test_subscribe_request_targets_print_stats_state() -> None:
    message = json.loads(klippy_subscribe.subscribe_request().rstrip(ETX).decode())
    assert message["method"] == "objects/subscribe"
    assert message["params"]["objects"] == {"print_stats": ["state"]}


def test_state_from_the_subscribe_reply_under_result() -> None:
    reply = {"id": 1, "result": {"status": {"print_stats": {"state": "printing"}}}}
    assert klippy_subscribe.state_from_frame(reply) == "printing"


def test_state_from_a_status_update_under_params() -> None:
    update = {"params": {"status": {"print_stats": {"state": "paused"}}, "eventtime": 1.0}}
    assert klippy_subscribe.state_from_frame(update) == "paused"


def test_state_is_none_when_the_frame_carries_no_print_stats() -> None:
    assert klippy_subscribe.state_from_frame({"params": {"status": {"toolhead": {}}}}) is None
    assert klippy_subscribe.state_from_frame({"id": 1, "result": {}}) is None


async def test_watch_pushes_each_state_then_reconnects_on_disconnect(socket_path: str) -> None:
    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(ETX)
        for state in ("printing", "complete"):
            writer.write(json.dumps({"params": {"status": {"print_stats": {"state": state}}}}).encode() + ETX)  # noqa: E501
        await writer.drain()
        writer.close()

    server = await asyncio.start_unix_server(serve, path=socket_path)
    async with server:
        seen = []
        async for state in klippy_subscribe.watch_print_state(socket_path):
            seen.append(state)
            if len(seen) == 3:
                break
    # the two live states, then "" when the server closed the connection (so a stale state cannot
    # stick across a Klipper restart).
    assert seen == ["printing", "complete", ""]
