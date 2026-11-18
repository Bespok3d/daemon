# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The runner reads a fake kernel log through the real record reader, so a test line travels the
whole way: read, named by the jinni, acted on."""
import logging
import threading
import time
from collections.abc import Generator, Iterator

import pytest

from core.watch import remedies
from core.watch.kmsg import read_messages
from core.watch.runner import WatchRunner
from core.watch.settings import WatchSettings, default_settings
from tests.core.watch.fake_watch import (
    ORDINARY_LINE,
    OTHER_LINE,
    OTHER_TOKEN,
    STUCK_LINE,
    STUCK_TOKEN,
    FakeKernelLog,
    FakeWatchJinni,
    OldJinni,
    RecordingHub,
    RefusingRebootJinni,
    use_jinni,
)

pytestmark = pytest.mark.usefixtures("quick_reboot")

READER_THREAD = "active-watch /dev/kmsg"


@pytest.fixture
def hub() -> RecordingHub:
    return RecordingHub()


@pytest.fixture
def runner(hub: RecordingHub, kernel_log: FakeKernelLog) -> Iterator[WatchRunner]:
    watch_runner = WatchRunner(hub, readers={"/dev/kmsg": _FakeKmsgReader(kernel_log)})
    yield watch_runner
    watch_runner.stop()


class _FakeKmsgReader:
    """Reads the fake kernel log the way the real reader reads /dev/kmsg once it is open."""

    def __init__(self, kernel_log: FakeKernelLog) -> None:
        self.kernel_log = kernel_log

    def __call__(self, path: str, wake_fd: int) -> Generator[str, None, None]:
        return read_messages(self.kernel_log.reader.fileno(), wake_fd)


def _reader_threads() -> list[threading.Thread]:
    return [thread for thread in threading.enumerate() if thread.name == READER_THREAD]


def test_a_recognised_state_is_acted_on_once_per_launch(
    monkeypatch: pytest.MonkeyPatch, runner: WatchRunner, hub: RecordingHub,
    kernel_log: FakeKernelLog,
) -> None:
    use_jinni(monkeypatch, FakeWatchJinni())
    runner.start(default_settings())
    for line in (ORDINARY_LINE, STUCK_LINE, STUCK_LINE, OTHER_LINE):
        kernel_log.log(line)
    assert hub.wait_for_frames(2) == [
        {"token": STUCK_TOKEN, "remedy": "notify"},
        {"token": OTHER_TOKEN, "remedy": "notify"},
    ]


def test_a_changed_setting_arms_the_state_again(
    monkeypatch: pytest.MonkeyPatch, runner: WatchRunner, hub: RecordingHub,
    kernel_log: FakeKernelLog,
) -> None:
    use_jinni(monkeypatch, FakeWatchJinni())
    runner.start(default_settings())
    kernel_log.log(STUCK_LINE)
    hub.wait_for_frames(1)
    rebooting: WatchSettings = {**default_settings(), "remedies": {STUCK_TOKEN: "reboot-when-idle"}}
    runner.restart(rebooting)
    kernel_log.log(STUCK_LINE)
    [_notified, rebooted] = hub.wait_for_frames(2)
    assert rebooted["remedy"] == "reboot"


def test_an_adapter_without_the_watch_stops_only_the_reader(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, runner: WatchRunner,
    hub: RecordingHub, kernel_log: FakeKernelLog,
) -> None:
    use_jinni(monkeypatch, OldJinni())
    caplog.set_level(logging.WARNING)
    runner.start(default_settings())
    [reader] = _reader_threads()
    kernel_log.log(STUCK_LINE)
    reader.join(timeout=5)
    assert not reader.is_alive()
    assert "the jinni failed" in caplog.text
    use_jinni(monkeypatch, FakeWatchJinni())
    runner.restart(default_settings())
    kernel_log.log(STUCK_LINE)
    assert hub.wait_for_frames(1) == [{"token": STUCK_TOKEN, "remedy": "notify"}]


def test_a_refused_reboot_keeps_the_watch_reading(
    monkeypatch: pytest.MonkeyPatch, runner: WatchRunner, hub: RecordingHub,
    kernel_log: FakeKernelLog,
) -> None:
    use_jinni(monkeypatch, RefusingRebootJinni())
    runner.start({**default_settings(), "remedies": {STUCK_TOKEN: "reboot-when-idle"}})
    kernel_log.log(STUCK_LINE)
    kernel_log.log(OTHER_LINE)
    [_announced, _taken_back, other] = hub.wait_for_frames(3)
    assert other == {"token": OTHER_TOKEN, "remedy": "notify"}


def test_a_changed_setting_takes_back_a_reboot_still_in_its_grace_at_once(
    monkeypatch: pytest.MonkeyPatch, runner: WatchRunner, hub: RecordingHub,
    kernel_log: FakeKernelLog,
) -> None:
    jinni = use_jinni(monkeypatch, FakeWatchJinni())
    monkeypatch.setattr(remedies, "REBOOT_NOTICE_GRACE_S", 60)
    runner.start({**default_settings(), "remedies": {STUCK_TOKEN: "reboot-when-idle"}})
    kernel_log.log(STUCK_LINE)
    hub.wait_for_frames(1)
    started = time.monotonic()
    runner.restart(default_settings())
    assert time.monotonic() - started < 5
    [announced, taken_back] = hub.frames
    assert taken_back == {"token": STUCK_TOKEN, "remedy": "notify", "id": announced["id"]}
    assert jinni.reboots_asked == 0


def test_stop_ends_every_reader(runner: WatchRunner) -> None:
    runner.start(default_settings())
    assert len(_reader_threads()) == 1
    runner.stop()
    assert _reader_threads() == []


def test_a_runner_never_started_stays_stopped_on_a_changed_setting(runner: WatchRunner) -> None:
    runner.restart(default_settings())
    assert _reader_threads() == []


def test_a_disabled_watch_reads_nothing(runner: WatchRunner) -> None:
    runner.start({**default_settings(), "enabled": False})
    assert _reader_threads() == []


def test_a_file_without_a_reader_is_skipped_with_a_warning(
    caplog: pytest.LogCaptureFixture, runner: WatchRunner,
) -> None:
    caplog.set_level(logging.WARNING)
    runner.start({**default_settings(), "files": ["/var/log/messages"]})
    assert _reader_threads() == []
    assert "/var/log/messages is not supported yet" in caplog.text
