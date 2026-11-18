# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio
import logging
from typing import cast

import pytest
from fastapi import WebSocket, WebSocketDisconnect

from api.routes.feed_relay import relay_until_client_closes


class SilentAppSocket:
    """An app that keeps its socket open and never sends, as every app on a feed does."""

    def __init__(self) -> None:
        self.closed = False

    async def receive_text(self) -> str:
        await asyncio.Event().wait()
        return ""

    async def close(self) -> None:
        self.closed = True


class ClosingAppSocket(SilentAppSocket):
    """An app that closes its socket, as the app does when the user leaves the view."""

    async def receive_text(self) -> str:
        raise WebSocketDisconnect


async def relay_that_waits(relay_stopped: asyncio.Event) -> None:
    try:
        await asyncio.Event().wait()
    finally:
        relay_stopped.set()


async def relay_that_breaks() -> None:
    raise ConnectionResetError("the app dropped the socket mid-send")


async def test_a_relay_that_fails_says_why_and_closes_the_socket(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app_socket = SilentAppSocket()
    with caplog.at_level(logging.INFO, logger="api.routes.feed_relay"):
        await relay_until_client_closes(cast(WebSocket, app_socket), relay_that_breaks())
    assert "the app dropped the socket mid-send" in caplog.text
    assert app_socket.closed


async def test_an_app_that_closes_its_socket_stops_the_relay() -> None:
    app_socket = ClosingAppSocket()
    relay_stopped = asyncio.Event()
    await relay_until_client_closes(cast(WebSocket, app_socket), relay_that_waits(relay_stopped))
    await asyncio.wait_for(relay_stopped.wait(), timeout=1)
    assert app_socket.closed
