# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Live active-watch frames to the app.

A reader thread calls `publish` from outside the event loop; delivery is marshalled onto the loop
thread with `call_soon_threadsafe`, so the subscriber queues are only ever touched there (the
pattern of `InstallProgressHub`). Nothing is replayed: a remedy is acted on whether or not the app
is listening.
"""
import asyncio

WatchFrame = dict[str, str]


class ActiveWatchHub:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[WatchFrame]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def publish(self, frame: WatchFrame) -> None:
        """Send a frame to every app listening. Safe to call from a reader thread. Before the first
        subscriber there is no loop and nobody to tell, and after the loop closed nobody is left to
        tell: either way the frame is dropped."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self._deliver, frame)

    def _deliver(self, frame: WatchFrame) -> None:
        for queue in self._subscribers:
            queue.put_nowait(frame)

    def subscribe(self) -> asyncio.Queue[WatchFrame]:
        self._loop = asyncio.get_running_loop()
        queue: asyncio.Queue[WatchFrame] = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[WatchFrame]) -> None:
        self._subscribers.discard(queue)
