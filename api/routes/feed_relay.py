# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The pieces every live feed shares: a relay from a hub queue to the app, the wait for the app to
close its socket (the app never sends on a feed), and running the two until either ends."""
import asyncio
import contextlib
import logging
from collections.abc import Coroutine
from typing import Any, TypeVar

from fastapi import WebSocket, WebSocketDisconnect

_log = logging.getLogger(__name__)

Frame = TypeVar("Frame")


async def wait_for_client_close(websocket: WebSocket) -> None:
    """Return when the app closes the socket (it never sends), so we can drop the relay side."""
    with contextlib.suppress(WebSocketDisconnect):
        while True:
            await websocket.receive_text()


async def relay_queue(websocket: WebSocket, queue: asyncio.Queue[Frame]) -> None:
    while True:
        await websocket.send_json(await queue.get())


async def relay_until_client_closes(
    websocket: WebSocket, relay: Coroutine[Any, Any, None],
) -> None:
    """Run the relay until it ends or the app goes away, then close the socket. The cancelled tasks
    are not awaited: a gather on them stays pending while they unwind, so a server cancelling this
    handler meanwhile cancels it twice and the cancellation escapes the server's own scope."""
    relay_task = asyncio.create_task(relay)
    close_task = asyncio.create_task(wait_for_client_close(websocket))
    relay_task.add_done_callback(_report_failure)
    close_task.add_done_callback(_report_failure)
    try:
        await asyncio.wait({relay_task, close_task}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        relay_task.cancel()
        close_task.cancel()
        await _close_quietly(websocket)


def _report_failure(task: asyncio.Task[None]) -> None:
    """Say why a side of the feed ended, if it failed, also when it failed while being cancelled.
    An app dropping the socket mid-send is the usual cause, so it is information, not a warning."""
    if not task.cancelled() and task.exception() is not None:
        _log.info("live feed ended: %r", task.exception())


async def _close_quietly(websocket: WebSocket) -> None:
    """The app has usually closed the socket already, so a failed close is routine."""
    try:
        await websocket.close()
    except Exception as close_failure:  # noqa: BLE001  any transport state may refuse the close
        _log.debug("live feed: the socket was already closed: %r", close_failure)
