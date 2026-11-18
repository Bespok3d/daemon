# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
import threading
from collections.abc import Callable, Iterator

import pytest

from core.watch import rebooting, remedies
from tests.core.watch.fake_watch import FakeKernelLog


class TimerTracker:
    """Starts the timers a remedy asks for and remembers them, so none outlives its test."""

    def __init__(self) -> None:
        self.timers: list[threading.Timer] = []

    def start_timer(
        self, interval: float, function: Callable[..., None], args: tuple[object, ...],
    ) -> threading.Timer:
        timer = threading.Timer(interval, function, args=args)
        self.timers.append(timer)
        return timer

    def cancel_all(self) -> None:
        for timer in self.timers:
            timer.cancel()


@pytest.fixture
def reboot_timers(monkeypatch: pytest.MonkeyPatch) -> Iterator[TimerTracker]:
    tracker = TimerTracker()
    monkeypatch.setattr(remedies, "Timer", tracker.start_timer)
    yield tracker
    tracker.cancel_all()


@pytest.fixture
def quick_reboot(monkeypatch: pytest.MonkeyPatch, reboot_timers: TimerTracker) -> None:
    """No grace before a reboot, no timer left running after the test, and no state left marked as
    being cleared by an earlier test's reboot."""
    monkeypatch.setattr(rebooting, "clearing", set())
    monkeypatch.setattr(remedies, "REBOOT_NOTICE_GRACE_S", 0)


@pytest.fixture
def kernel_log() -> Iterator[FakeKernelLog]:
    log = FakeKernelLog()
    yield log
    log.close()
