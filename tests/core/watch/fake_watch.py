# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The fakes the active-watch tests share: a jinni that names one opaque kernel line per state and
records the reboots it is asked for, a hub that records the frames it would send, and a kernel log
made of a datagram socket pair, which hands back one record per read as /dev/kmsg does."""
import socket
import threading

import pytest

import protocol
from core import jinni_client
from core.watch.hub import ActiveWatchHub, WatchFrame

STUCK_TOKEN = "screen-stuck"
OTHER_TOKEN = "other-state"
STUCK_LINE = "a line naming the stuck state"
OTHER_LINE = "a line naming the other state"
ORDINARY_LINE = "an ordinary kernel line"
STATE_BY_LINE = {STUCK_LINE: STUCK_TOKEN, OTHER_LINE: OTHER_TOKEN}


def kmsg_record(message: str, sequence: int = 1) -> bytes:
    """One record as /dev/kmsg hands it out, with a continuation line under the message."""
    return f"3,{sequence},1000,-;{message}\n SUBSYSTEM=test\n".encode()


class FakeWatchJinni:
    def __init__(self, blocked: frozenset[str] = frozenset()) -> None:
        self.blocked = blocked
        self.reboots_asked = 0

    def watch_line(self, line: str) -> str | None:
        return STATE_BY_LINE.get(line)

    def blocked_actions(self) -> frozenset[str]:
        return self.blocked

    def reboot_printer(self) -> None:
        self.reboots_asked += 1


class OldJinni(FakeWatchJinni):
    """An adapter older than the watch: it has no `watch_line` verb and refuses it."""

    def watch_line(self, line: str) -> str | None:
        raise protocol.ProtocolError("unknown verb: watch_line")


class RefusingRebootJinni(FakeWatchJinni):
    def reboot_printer(self) -> None:
        raise protocol.ProtocolError("reboot refused")


def use_jinni(monkeypatch: pytest.MonkeyPatch, jinni: FakeWatchJinni) -> FakeWatchJinni:
    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", lambda: jinni)
    return jinni


class RecordingHub(ActiveWatchHub):
    """Records the frames instead of sending them; the real delivery is tested on its own."""

    def __init__(self) -> None:
        super().__init__()
        self.frames: list[WatchFrame] = []
        self._new_frame = threading.Condition()

    def publish(self, frame: WatchFrame) -> None:
        with self._new_frame:
            self.frames.append(frame)
            self._new_frame.notify_all()

    def wait_for_frames(self, count: int) -> list[WatchFrame]:
        with self._new_frame:
            arrived = self._new_frame.wait_for(lambda: len(self.frames) >= count, timeout=5)
            assert arrived, f"waited for {count} frames, got {self.frames}"
            return list(self.frames)


class FakeKernelLog:
    """The reader end stands for the opened /dev/kmsg; the writer end is the kernel logging."""

    def __init__(self) -> None:
        self.reader, self.writer = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)

    def log(self, message: str) -> None:
        self.writer.send(kmsg_record(message))

    def close(self) -> None:
        self.reader.close()
        self.writer.close()
