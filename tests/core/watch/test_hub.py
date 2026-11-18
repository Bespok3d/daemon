# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio
import threading

from core.watch.hub import ActiveWatchHub, WatchFrame

NOTIFY_FRAME: WatchFrame = {"token": "screen-stuck", "remedy": "notify"}


async def subscribe(hub: ActiveWatchHub) -> asyncio.Queue[WatchFrame]:
    return hub.subscribe()


async def test_a_frame_published_from_a_reader_thread_reaches_the_app() -> None:
    hub = ActiveWatchHub()
    app_queue = hub.subscribe()
    reader = threading.Thread(target=hub.publish, args=(NOTIFY_FRAME,))
    reader.start()
    reader.join()
    assert await asyncio.wait_for(app_queue.get(), timeout=5) == NOTIFY_FRAME


def test_a_frame_published_before_any_app_listened_is_dropped() -> None:
    hub = ActiveWatchHub()
    hub.publish(NOTIFY_FRAME)
    loop = asyncio.new_event_loop()
    try:
        app_queue = loop.run_until_complete(subscribe(hub))
        loop.run_until_complete(asyncio.sleep(0))
        assert app_queue.empty()
    finally:
        loop.close()


def test_a_frame_published_after_the_loop_closed_is_dropped() -> None:
    hub = ActiveWatchHub()
    loop = asyncio.new_event_loop()
    app_queue = loop.run_until_complete(subscribe(hub))
    loop.close()
    hub.publish(NOTIFY_FRAME)
    assert app_queue.empty()
