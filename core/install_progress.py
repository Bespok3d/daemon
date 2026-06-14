"""Live install-progress fan-out.

The install runs off the event loop (`asyncio.to_thread`) so its phases can be streamed as they
finish. The worker thread calls `publish` from outside the loop; delivery is marshalled back onto
the loop thread via `call_soon_threadsafe` so the subscriber queues and buffer are only ever touched
there. A buffer of the IN-PROGRESS run's events is replayed to a late subscriber, so a client that
connects after the first phase has already fired does not miss it (connect-vs-first-event race).

Only an ACTIVE run replays. The app opens a fresh socket just before each install POST; if a
finished run still replayed, that socket would receive the previous run's whole phase list before
its own began (the duplicate-steps bug). `begin` opens a run (active, empty buffer); the terminal
`done` closes it, so a socket opened between installs replays nothing and waits for the next
`begin`.
"""

import asyncio


class InstallProgressHub:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict]] = set()
        self._buffer: list[dict] = []
        self._active = False
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def begin(self) -> None:
        """Open a fresh run: mark active, drop the previous run's buffer, and drain any already
        connected subscriber's queue so no stale event from a prior run survives into this one."""
        self._buffer = []
        self._active = True
        for queue in self._subscribers:
            while not queue.empty():
                queue.get_nowait()

    def publish(self, event: dict) -> None:
        """Announce an event. Safe to call from a worker thread: delivery is marshalled onto the
        loop thread, where the buffer and subscriber queues live."""
        loop = self._loop
        if loop is None:
            return
        loop.call_soon_threadsafe(self._deliver, event)

    def _deliver(self, event: dict) -> None:
        self._buffer.append(event)
        if event.get("type") == "done":
            self._active = False
        for queue in self._subscribers:
            queue.put_nowait(event)

    def subscribe(self) -> asyncio.Queue[dict]:
        """Register a subscriber, replaying the events of an IN-PROGRESS run so far (nothing once
        the run has finished). Runs on the loop thread, serialized against `_deliver`, so no event
        slips through between replay and registration."""
        self._loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict] = asyncio.Queue()
        if self._active:
            for event in self._buffer:
                queue.put_nowait(event)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict]) -> None:
        self._subscribers.discard(queue)
