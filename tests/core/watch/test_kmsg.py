# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from core.watch import kmsg
from tests.core.watch.fake_watch import FakeKernelLog, kmsg_record


class _OverrunOnce:
    """The first read of the log fails the way /dev/kmsg tells a reader it fell behind."""

    def __init__(self, kmsg_fd: int, real_read: Callable[[int, int], bytes]) -> None:
        self.kmsg_fd = kmsg_fd
        self.real_read = real_read
        self.overran = False

    def __call__(self, fd: int, size: int) -> bytes:
        if fd == self.kmsg_fd and not self.overran:
            self.overran = True
            raise BrokenPipeError
        return self.real_read(fd, size)


@pytest.fixture
def wake_pipe() -> Iterator[tuple[int, int]]:
    wake_read_fd, wake_write_fd = os.pipe()
    yield wake_read_fd, wake_write_fd
    os.close(wake_read_fd)
    os.close(wake_write_fd)


def test_a_record_s_message_drops_its_header_and_dictionary() -> None:
    assert kmsg.record_message(kmsg_record("vp0 failed; to attach")) == "vp0 failed; to attach"


def test_each_record_reads_as_one_line(
    kernel_log: FakeKernelLog, wake_pipe: tuple[int, int],
) -> None:
    kernel_log.log("first line")
    kernel_log.log("second line")
    messages = kmsg.read_messages(kernel_log.reader.fileno(), wake_pipe[0])
    assert [next(messages), next(messages)] == ["first line", "second line"]


def test_a_write_to_the_wake_pipe_ends_the_reading(
    kernel_log: FakeKernelLog, wake_pipe: tuple[int, int],
) -> None:
    messages = kmsg.read_messages(kernel_log.reader.fileno(), wake_pipe[0])
    os.write(wake_pipe[1], b"x")
    assert list(messages) == []


def test_a_stop_wins_over_a_line_still_waiting(
    kernel_log: FakeKernelLog, wake_pipe: tuple[int, int],
) -> None:
    kernel_log.log("a line logged as the watch stops")
    os.write(wake_pipe[1], b"x")
    assert list(kmsg.read_messages(kernel_log.reader.fileno(), wake_pipe[0])) == []


def test_a_reader_that_fell_behind_says_so_and_reads_on(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    kernel_log: FakeKernelLog, wake_pipe: tuple[int, int],
) -> None:
    overrun = _OverrunOnce(kernel_log.reader.fileno(), os.read)
    monkeypatch.setattr(kmsg.os, "read", overrun)
    kernel_log.log("line after the overrun")
    messages = kmsg.read_messages(kernel_log.reader.fileno(), wake_pipe[0])
    assert next(messages) == "line after the overrun"
    assert overrun.overran
    assert "some lines were missed" in caplog.text


def test_the_log_opens_after_its_newest_record(tmp_path: Path) -> None:
    log_file = tmp_path / "log"
    log_file.write_bytes(kmsg_record("an old line"))
    log_fd = kmsg.open_at_end(str(log_file))
    try:
        assert os.read(log_fd, kmsg.RECORD_BUFFER_BYTES) == b""
    finally:
        os.close(log_fd)
