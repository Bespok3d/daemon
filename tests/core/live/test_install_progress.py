# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio
import threading

import pytest

from core.live.install_progress import InstallProgressHub


@pytest.mark.asyncio
async def test_subscriber_receives_published_events_in_order() -> None:
    hub = InstallProgressHub()
    hub.bind_loop(asyncio.get_running_loop())
    hub.begin()
    queue = hub.subscribe()
    hub.publish({"type": "phase", "phase": {"id": "extract"}})
    hub.publish({"type": "done", "ok": True})
    first = await asyncio.wait_for(queue.get(), timeout=1)
    second = await asyncio.wait_for(queue.get(), timeout=1)
    assert first == {"type": "phase", "phase": {"id": "extract"}}
    assert second == {"type": "done", "ok": True}


@pytest.mark.asyncio
async def test_late_subscriber_replays_current_run() -> None:
    hub = InstallProgressHub()
    hub.bind_loop(asyncio.get_running_loop())
    hub.begin()
    hub.publish({"type": "phase", "phase": {"id": "symlinks"}})
    await asyncio.sleep(0)  # let call_soon_threadsafe drain onto the buffer
    queue = hub.subscribe()
    replayed = await asyncio.wait_for(queue.get(), timeout=1)
    assert replayed == {"type": "phase", "phase": {"id": "symlinks"}}


@pytest.mark.asyncio
async def test_begin_drops_the_previous_runs_buffer() -> None:
    hub = InstallProgressHub()
    hub.bind_loop(asyncio.get_running_loop())
    hub.begin()
    hub.publish({"type": "done", "ok": True})
    await asyncio.sleep(0)
    hub.begin()
    queue = hub.subscribe()
    assert queue.empty()


@pytest.mark.asyncio
async def test_a_socket_opened_after_a_finished_run_replays_nothing() -> None:
    # The duplicate-steps bug: the app opens a fresh socket before each install POST. A finished
    # prior run must NOT replay, or the new socket shows the previous run's whole phase list first.
    hub = InstallProgressHub()
    hub.bind_loop(asyncio.get_running_loop())
    hub.begin()
    hub.publish({"type": "phase", "phase": {"id": "extract"}})
    hub.publish({"type": "done", "ok": True})
    await asyncio.sleep(0)
    queue = hub.subscribe()
    assert queue.empty()


@pytest.mark.asyncio
async def test_begin_drains_a_still_connected_subscribers_queue() -> None:
    # Defensive: if a subscriber connected during an active run still holds undelivered events when
    # a new run opens, begin() drains them so the next run starts clean for that subscriber too.
    hub = InstallProgressHub()
    hub.bind_loop(asyncio.get_running_loop())
    hub.begin()
    queue = hub.subscribe()
    hub._deliver({"type": "phase", "phase": {"id": "stale"}})
    assert not queue.empty()
    hub.begin()
    assert queue.empty()
    hub._deliver({"type": "phase", "phase": {"id": "extract"}})
    event = await asyncio.wait_for(queue.get(), timeout=1)
    assert event == {"type": "phase", "phase": {"id": "extract"}}


@pytest.mark.asyncio
async def test_publish_from_a_worker_thread_is_marshalled_to_the_loop() -> None:
    hub = InstallProgressHub()
    hub.bind_loop(asyncio.get_running_loop())
    hub.begin()
    queue = hub.subscribe()

    def worker() -> None:
        hub.publish({"type": "phase", "phase": {"id": "patches"}})

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    event = await asyncio.wait_for(queue.get(), timeout=1)
    assert event == {"type": "phase", "phase": {"id": "patches"}}


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery() -> None:
    hub = InstallProgressHub()
    hub.bind_loop(asyncio.get_running_loop())
    hub.begin()
    queue = hub.subscribe()
    hub.unsubscribe(queue)
    hub.publish({"type": "done", "ok": True})
    await asyncio.sleep(0)
    assert queue.empty()


def test_publish_without_a_bound_loop_is_a_noop() -> None:
    hub = InstallProgressHub()
    hub.publish({"type": "done", "ok": True})  # must not raise
