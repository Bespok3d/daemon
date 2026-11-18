# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reading the kernel log live from /dev/kmsg, from the newest record on, one record per read.

Per the kernel's dev-kmsg ABI a read returns exactly one record, `<prio>,<seq>,<usec>,<flags>;`
followed by the message and its continuation lines; a read blocks until a record arrives; and a
reader that fell behind gets EPIPE once, then reads on from the oldest record still kept.
"""
import logging
import os
import select
from collections.abc import Generator

_log = logging.getLogger(__name__)

RECORD_BUFFER_BYTES = 8192


def record_message(record: bytes) -> str:
    """The message of one record: the text after the first `;`, first line only (the lines after it
    are the record's key=value dictionary)."""
    text = record.decode("utf-8", errors="replace")
    return text.partition(";")[2].split("\n", 1)[0]


def open_at_end(path: str) -> int:
    """Open the log positioned after its newest record, so only lines logged from now on are read;
    the ones already there were judged by the boot-time reboot check."""
    kmsg_fd = os.open(path, os.O_RDONLY)
    try:
        os.lseek(kmsg_fd, 0, os.SEEK_END)
    except OSError:
        os.close(kmsg_fd)
        raise
    return kmsg_fd


def _read_record(kmsg_fd: int) -> bytes | None:
    """One record, or None when the reader fell behind and the kernel overwrote records. The next
    read goes on from the oldest kept record, so the loss is logged and reading continues."""
    try:
        return os.read(kmsg_fd, RECORD_BUFFER_BYTES)
    except BrokenPipeError:
        _log.warning("active watch: the kernel log overran the reader, some lines were missed")
        return None


def read_messages(kmsg_fd: int, wake_fd: int) -> Generator[str, None, None]:
    """Each new record's message, until the wake pipe is written to or the log ends. Waiting on
    both at once lets a stop end the read at once. `poll`, not `select`: the daemon's descriptor
    numbers are not bounded by select's 1024."""
    readiness = select.poll()
    readiness.register(kmsg_fd, select.POLLIN)
    readiness.register(wake_fd, select.POLLIN)
    while True:
        ready_fds = [ready_fd for ready_fd, _event in readiness.poll()]
        if wake_fd in ready_fds:
            return
        record = _read_record(kmsg_fd)
        if record == b"":
            return
        if record is not None:
            yield record_message(record)


def kmsg_messages(path: str, wake_fd: int) -> Generator[str, None, None]:
    kmsg_fd = open_at_end(path)
    try:
        yield from read_messages(kmsg_fd, wake_fd)
    finally:
        os.close(kmsg_fd)
