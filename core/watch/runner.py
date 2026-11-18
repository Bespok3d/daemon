# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The reader threads of the active watch: one per watched file, each relaying every new line to
the jinni and carrying out the remedy for a state it recognises.

A read blocks, so each reader is a daemon thread. A stop writes to a shared wake pipe that every
reader waits on beside its file, so all of them end at once and are joined before the files close.
It also sets the launch's stopping event, so a reboot still in its grace is taken back at once
instead of holding up the stop.

A recognised state is acted on once per launch: the latched state keeps the jinni naming it on
every later line of the same fault, and one remedy is all the user asked for. A changed setting
relaunches the readers and so arms each state again.
"""
import contextlib
import logging
import os
import threading
from collections.abc import Iterator, Mapping

import protocol

from .. import jinni_client
from .hub import ActiveWatchHub
from .readers import READERS, MessageSource, supported_sources
from .remedies import apply_remedy
from .settings import WatchSettings

_log = logging.getLogger(__name__)


class WatchRunner:
    def __init__(
        self, hub: ActiveWatchHub, readers: Mapping[str, MessageSource] = READERS,
    ) -> None:
        self._hub = hub
        self._readers = readers
        self._lifecycle_lock = threading.Lock()
        self._allowed = False
        self._threads: list[threading.Thread] = []
        self._wake: tuple[int, int] | None = None
        self._stopping = threading.Event()
        self._fired_lock = threading.Lock()
        self._fired: set[str] = set()

    def start(self, settings: WatchSettings) -> None:
        """Start watching. Only the printer's daemon calls this, at startup, so a dev or test run
        never reads the host's kernel log."""
        with self._lifecycle_lock:
            self._allowed = True
            self._relaunch(settings)

    def restart(self, settings: WatchSettings) -> None:
        """Apply a changed setting. A runner that was never started stays stopped."""
        with self._lifecycle_lock:
            if self._allowed:
                self._relaunch(settings)

    def stop(self) -> None:
        with self._lifecycle_lock:
            self._allowed = False
            self._halt()

    def _relaunch(self, settings: WatchSettings) -> None:
        self._halt()
        self._launch(settings)

    def _halt(self) -> None:
        if self._wake is None:
            return
        wake_read_fd, wake_write_fd = self._wake
        self._stopping.set()
        os.write(wake_write_fd, b"x")
        for thread in self._threads:
            thread.join()
        os.close(wake_read_fd)
        os.close(wake_write_fd)
        self._threads = []
        self._wake = None

    def _launch(self, settings: WatchSettings) -> None:
        if not settings["enabled"]:
            return
        with self._fired_lock:
            self._fired = set()
        sources = supported_sources(settings["files"], self._readers)
        self._wake = os.pipe()
        self._stopping = threading.Event()
        wake_read_fd = self._wake[0]
        self._threads = [
            threading.Thread(
                target=self._watch, args=(path, source, wake_read_fd, settings, self._stopping),
                name=f"active-watch {path}", daemon=True,
            )
            for path, source in sources
        ]
        for thread in self._threads:
            thread.start()

    def _watch(
        self, path: str, source: MessageSource, wake_read_fd: int, settings: WatchSettings,
        stopping: threading.Event,
    ) -> None:
        """One reader's whole life. A failure stops this reader only: the others and the daemon
        carry on, and the log says why this file is no longer watched."""
        try:
            with contextlib.closing(source(path, wake_read_fd)) as messages:
                self._relay(messages, settings, stopping)
        except protocol.ProtocolError as error:
            _log.warning("active watch: stopped watching %s, the jinni failed: %s", path, error)
        except OSError:
            _log.exception("active watch: stopped watching %s", path)

    def _relay(
        self, messages: Iterator[str], settings: WatchSettings, stopping: threading.Event,
    ) -> None:
        for message in messages:
            token = jinni_client.watch_line(message)
            if token is not None and self._first_sighting(token):
                remedy = settings["remedies"].get(token, "notify")
                apply_remedy(token, remedy, self._hub, stopping)

    def _first_sighting(self, token: str) -> bool:
        with self._fired_lock:
            if token in self._fired:
                return False
            self._fired.add(token)
            return True
